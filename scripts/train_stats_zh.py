"""Train stats_zh.json baseline at 5500 Hz Praat formant ceiling.

Background
----------
The legacy stats_zh.json was extracted at Praat's male-default 5000 Hz
ceiling.  Phase A (tests/reports/zh_resonance_baseline_2026-05-01.md)
showed the same /i/ F2 collapse that motivated adaptive ceiling for fr —
female /i/ F2 measures 1523 Hz vs literature 2700 Hz (56 %).  Re-training
at 5500 Hz lifts the ceiling above the female /i/ F2 zone so the LPC
solver stops fusing F1+F2 into a spurious low-frequency peak.

Once this stats file is committed and zh is added to ``_ADAPTIVE_LANGS``
in wrapper/ceiling_selector.py, the runtime selector picks 4500–6500 Hz
per-recording.  Stats baked at 5500 Hz means recordings the selector
chooses to evaluate at higher ceilings will read a touch more "female"
(positive z_F2) — acceptable because the selector only goes higher when
within-vowel CV says higher is more reliable.

Designed to run inside the sidecar container (so it can call vendored
preprocessing / phones / ceiling_selector directly without HTTP).

Usage (host shell)::

    docker run --rm \
      -v /mnt/d/project_vocieduck/ablation/audio/cn/AISHELL3:/mnt/aishell3:ro \
      -v $(pwd)/scripts:/host_scripts:ro \
      -v $HOME/scratch/zh_stats_train:/output:rw \
      --entrypoint "" \
      voice-gender-analyzer-visualizer-backend \
      micromamba run -n mfa python /host_scripts/train_stats_zh.py \
        --aishell /mnt/aishell3 \
        --out /output/stats_zh_5500.json \
        --ceiling 5500 \
        --n-segments 5000 \
        --num-workers 8

Resumable: checkpoint JSONL is appended-to per phone observation.
Re-running with the same checkpoint skips audio paths already processed.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

# /app is the vendored visualizer-backend root inside the container; that's
# where preprocessing / phones / settings.json / mandarin_china_mfa live.
sys.path.insert(0, "/app")

import acousticgender.library.phones as phones  # noqa: E402
from acousticgender.library.settings import settings  # noqa: E402
from wrapper import ceiling_selector  # noqa: E402
from wrapper.preloaded_aligner import PreloadedAligner  # noqa: E402

# preprocessing.process() is the legacy subprocess-MFA path; kalpy alignment
# below replaces it entirely.  Subprocess MFA has two issues with this corpus:
#   (1) ~10 s startup per call kills throughput,
#   (2) 8-way concurrency races on
#       /opt/conda/.../spacy_pkuseg/postag/w.npy → BadZipFile (CRC mismatch).
# kalpy's PreloadedAligner doesn't touch spacy_pkuseg (zh path tokenises
# hanzi-by-hanzi inline), and amortises the model load across the worker's
# lifetime (~30 s once, sub-second per align).

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("train_stats_zh")

_MIN_DURATION_SEC = 2.5  # AISHELL-3 clips skew shorter than CV (median ~5 s)
_MAX_DURATION_SEC = 12.0
# Per-phoneme obs gate.  Mandarin has ~50 phone classes total in
# mandarin_china_mfa, so 5000 segments × ~30-50 phones/segment yields
# 3000-7500 obs for common phones — well above 200.  Lower-frequency
# phones (零韵母 ʐ̩ z̩, ɥ) may fall below; gate drops them silently and
# resonance.compute_resonance falls back to no-stats for those.
_MIN_OBS_PER_PHONEME = 200

_CJK_RE = re.compile(r"[一-鿿]")

# IPA tone diacritics stripped before bucketing — resonance.compute_resonance
# at runtime keys stats lookups by ``_strip_tone(expected)`` for zh, so the
# trained stats must use tone-stripped keys to match.  Tones primarily
# colour F0; F1/F2/F3 are mostly tone-independent, so merging across tones
# is the right call for formant statistics.
_TONE_RE = re.compile(r"[˥˦˧˨˩]+")


# ── corpus parsing (mirrors scripts/audit_resonance_zh.py) ──────────


def parse_spk_info(aishell_root: Path) -> dict[str, dict]:
    info_path = aishell_root / "spk-info.txt"
    out: dict[str, dict] = {}
    for line in info_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        spk, age, gender, accent = parts[0], parts[1], parts[2], parts[3]
        out[spk] = {"age": age, "gender": gender, "accent": accent}
    return out


def parse_content(aishell_root: Path) -> dict[str, str]:
    """wav_filename → CJK-only transcript.  Pools train/ + test/ since
    AISHELL-3 splits are by speaker, not by stats target."""
    out: dict[str, str] = {}
    for split in ("train", "test"):
        content_path = aishell_root / split / "content.txt"
        if not content_path.is_file():
            continue
        for line in content_path.read_text(encoding="utf-8").splitlines():
            if "\t" not in line:
                continue
            wav, body = line.split("\t", 1)
            chars = _CJK_RE.findall(body)
            if chars:
                out[wav] = "".join(chars)
    return out


def _audio_duration_ok(path: Path) -> bool:
    try:
        import wave  # noqa: PLC0415

        with wave.open(str(path), "rb") as w:
            dur = w.getnframes() / float(w.getframerate())
        return _MIN_DURATION_SEC <= dur <= _MAX_DURATION_SEC
    except Exception as exc:
        logger.debug("duration check failed for %s: %s", path, exc)
        return False


def _enumerate_clips(
    aishell_root: Path, spk_info: dict[str, dict], transcripts: dict[str, str]
) -> list[dict]:
    """List every wav that has a known transcript and a labeled speaker.

    Returns rows with ``client_id`` (spk), ``audio_path``, ``sentence``,
    ``gender_short`` — same shape ``train_stats_fr.py`` consumes.
    """
    rows: list[dict] = []
    for split in ("train", "test"):
        wav_root = aishell_root / split / "wav"
        if not wav_root.is_dir():
            continue
        for spk_dir in wav_root.iterdir():
            if not spk_dir.is_dir():
                continue
            spk = spk_dir.name
            meta = spk_info.get(spk)
            if not meta:
                continue
            gender = meta["gender"]
            if gender not in ("male", "female"):
                continue
            for wav in spk_dir.glob("*.wav"):
                sent = transcripts.get(wav.name)
                if not sent:
                    continue
                rows.append(
                    {
                        "client_id": spk,
                        "audio_path": str(wav),
                        "sentence": sent,
                        "gender_short": gender,
                    }
                )
    return rows


def _sample_balanced(
    rows: list[dict], n_target: int, max_per_speaker: int, seed: int
) -> list[dict]:
    """Round-robin pick from male/female speaker buckets, capping per-speaker."""
    rng = random.Random(seed)
    by_speaker: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_speaker[(r["client_id"], r["gender_short"])].append(r)
    speakers_male = [k for k in by_speaker if k[1] == "male"]
    speakers_female = [k for k in by_speaker if k[1] == "female"]
    rng.shuffle(speakers_male)
    rng.shuffle(speakers_female)
    logger.info("speaker pools: %d male, %d female", len(speakers_male), len(speakers_female))
    # Round-robin male/female so the sample stays gender-balanced even if
    # one side runs out (AISHELL-3 has 4× more female than male spk).
    picked: list[dict] = []
    pools = [iter(speakers_male), iter(speakers_female)]
    pool_idx = 0
    while len(picked) < n_target:
        key = next(pools[pool_idx], None)
        if key is None:
            # this side exhausted — try the other
            other = 1 - pool_idx
            other_key = next(pools[other], None)
            if other_key is None:
                break
            picked.extend(by_speaker[other_key][:max_per_speaker])
            pool_idx = other
            continue
        picked.extend(by_speaker[key][:max_per_speaker])
        pool_idx = 1 - pool_idx
    rng.shuffle(picked)
    return picked[:n_target]


# ── per-segment processing ─────────────────────────────────────────


# Worker-local state — populated in ``_pool_worker_init`` after fork so
# every Kaldi/lexicon object is owned by one process and never crosses the
# multiprocessing pickle boundary (none of these are picklable).
_WORKER_ALIGNER: PreloadedAligner | None = None
_WORKER_PRAAT_BIN: str | None = None
_WORKER_PRAAT_SCRIPT: str | None = None


def _process_one(audio_path: str, transcript: str, ceiling_hz: int) -> list[dict] | None:
    """Run kalpy alignment + Praat formant extraction on one wav, pin to
    ``ceiling_hz``, return list of {phoneme, F: [F0, F1, F2, F3]} dicts.
    """
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    if not transcript:
        return None

    aligner = _WORKER_ALIGNER
    praat_bin = _WORKER_PRAAT_BIN
    praat_script = _WORKER_PRAAT_SCRIPT
    if aligner is None or praat_bin is None or praat_script is None:
        logger.error("worker state not initialised — _pool_worker_init not run?")
        return None

    src_path = Path(audio_path)
    # PreloadedAligner.align_one writes a tempfile next to the wav (it builds
    # an MFA-style corpus dir on the fly), which fails when ``/mnt/aishell3``
    # is mounted read-only.  Copy the wav into a per-call writable tmpdir so
    # both the aligner and Praat can scribble alongside it.
    with tempfile.TemporaryDirectory(prefix="train_zh_") as tmp:
        wav_path = Path(tmp) / src_path.name
        try:
            shutil.copy2(src_path, wav_path)
        except OSError as exc:
            logger.debug("wav copy failed for %s: %s", audio_path, exc)
            return None
        grid_path = Path(tmp) / "out.TextGrid"
        try:
            aligner.align_one(wav_path, transcript, grid_path)
        except Exception as exc:
            logger.debug("kalpy align failed for %s: %s", audio_path, exc)
            return None

        try:
            praat_raw = subprocess.check_output(  # noqa: S603 — args are paths
                [praat_bin, "--run", praat_script, str(wav_path), str(grid_path)],
                stderr=subprocess.STDOUT,
                timeout=30,
            ).decode("utf-8")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.debug("praat failed for %s: %s", audio_path, exc)
            return None

    # kalpy emits "<eps>" for silence; phones.parse expects MFA's "" form.
    # Mirrors the normalisation in wrapper/multichunk.run_praat_per_chunk.
    praat_raw = praat_raw.replace("\t<eps>", "\t")
    praat_raw = ceiling_selector.rewrite_to_ceiling(praat_raw, ceiling_hz)

    try:
        data = phones.parse(praat_raw, "zh")
    except Exception as exc:
        logger.debug("phones.parse failed for %s: %s", audio_path, exc)
        return None

    out: list[dict] = []
    for p in data.get("phones") or []:
        phoneme_raw = p.get("phoneme")
        formants = p.get("F") or []
        if not phoneme_raw or len(formants) < 4:
            continue
        phoneme = _TONE_RE.sub("", phoneme_raw)
        if not phoneme:
            continue
        out.append(
            {
                "phoneme": phoneme,
                "F": [float(v) if v is not None else None for v in formants[:4]],
            }
        )
    return out


def _process_one_safe(args: tuple[str, str, int]) -> tuple[str, list[dict] | None]:
    audio_path, transcript, ceiling_hz = args
    return audio_path, _process_one(audio_path, transcript, ceiling_hz)


def _pool_worker_init() -> None:
    """Initialise per-worker kalpy aligner + Praat paths after fork.

    Loading the acoustic model + lexicon FST takes ~20–30 s the first time
    (re-used from the on-disk cache on subsequent worker starts).  We accept
    that one-off cost per worker because it amortises across hundreds of
    align_one calls at sub-second each.
    """
    global _WORKER_ALIGNER, _WORKER_PRAAT_BIN, _WORKER_PRAAT_SCRIPT

    # Per-worker MFA_ROOT_DIR — without this, 8 workers race on
    # ``$MFA_ROOT_DIR/extracted_models/acoustic/mandarin_mfa_acoustic/``
    # extraction (concurrent ``os.makedirs(..., exist_ok=False)``) and most
    # of them blow up with ``FileExistsError: mandarin_mfa``.  Each worker
    # gets its own MFA root pointing at a private extraction dir; the
    # pretrained_models cache is symlinked from the shared system cache so
    # we don't re-download the 200 MB acoustic model per worker.
    pid = os.getpid()
    mfa_root = f"/tmp/mfa_worker_{pid}"
    os.makedirs(mfa_root, exist_ok=True)
    src_pretrained = "/opt/mfa_root/pretrained_models"
    dst_pretrained = os.path.join(mfa_root, "pretrained_models")
    if not os.path.exists(dst_pretrained) and os.path.exists(src_pretrained):
        os.symlink(src_pretrained, dst_pretrained)
    os.environ["MFA_ROOT_DIR"] = mfa_root

    from montreal_forced_aligner.models import (  # noqa: PLC0415
        MODEL_TYPES as _MFA_MODEL_TYPES,
    )

    acoustic_path = _MFA_MODEL_TYPES["acoustic"].get_pretrained_path("mandarin_mfa")
    # mandarin_china_mfa is the v3-aligned dict (matches main.py's
    # _DICT_NAME_BY_LANG["zh"]).  See main.py:192-201 for context.
    dict_path = _MFA_MODEL_TYPES["dictionary"].get_pretrained_path("mandarin_china_mfa")
    aligner = PreloadedAligner.load("zh", acoustic_path, dict_path)
    if aligner is None:
        raise RuntimeError("PreloadedAligner.load returned None for zh — see logs")
    # Warmup: pay the kalpy/Kaldi JIT cost once per worker so the first real
    # segment doesn't time out.  Best-effort; failures are non-fatal because
    # the warmup transcript ("你好") on silent audio is known to exhaust
    # beam=50 in some kalpy versions.  See preloaded_aligner.warmup docstring.
    aligner.warmup()
    _WORKER_ALIGNER = aligner
    _WORKER_PRAAT_BIN = settings["praat"]
    _WORKER_PRAAT_SCRIPT = "/app/textgrid-formants.praat"
    logger.info("worker pid=%d kalpy aligner ready", os.getpid())


# ── aggregation ────────────────────────────────────────────────────


def _aggregate_to_stats(checkpoint_path: Path, out_path: Path) -> None:
    """Read JSONL of phoneme observations and produce stats_zh.json.

    Schema matches the existing stats_zh.json: ``{phoneme: [{mean, stdev,
    median, max, min}, x4]}`` where x4 is [F0, F1, F2, F3].  Phonemes with
    < _MIN_OBS_PER_PHONEME at F1+F2 are dropped (resonance.compute_resonance
    falls back to no-stats for missing phonemes).
    """
    by_phoneme: dict[str, list[list[float | None]]] = defaultdict(list)
    with checkpoint_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_phoneme[row["phoneme"]].append(row["F"])

    stats: dict[str, list[dict]] = {}
    dropped: list[tuple[str, int, int]] = []
    for phoneme, observations in by_phoneme.items():
        per_formant: list[dict | None] = []
        for i in range(4):
            values = [o[i] for o in observations if o[i] is not None]
            if len(values) < _MIN_OBS_PER_PHONEME:
                per_formant.append(None)
                continue
            per_formant.append(
                {
                    "mean": statistics.mean(values),
                    "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "median": statistics.median(values),
                    "max": max(values),
                    "min": min(values),
                }
            )
        # Need F1 + F2 minimum for resonance to compute anything useful.
        if per_formant[1] is None or per_formant[2] is None:
            dropped.append(
                (
                    phoneme,
                    sum(1 for o in observations if o[1] is not None),
                    sum(1 for o in observations if o[2] is not None),
                )
            )
            continue
        stats[phoneme] = [
            fmt
            if fmt is not None
            else {"mean": 0.0, "stdev": 1.0, "median": 0.0, "max": 0.0, "min": 0.0}
            for fmt in per_formant
        ]

    for phoneme, n_f1, n_f2 in dropped:
        logger.info(
            "dropped phoneme %r: F1 obs=%d, F2 obs=%d (< %d)",
            phoneme,
            n_f1,
            n_f2,
            _MIN_OBS_PER_PHONEME,
        )

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)
    logger.info("wrote %s with %d phonemes (%d dropped)", out_path, len(stats), len(dropped))


# ── cli ────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Train stats_zh.json at a fixed Praat ceiling")
    ap.add_argument("--aishell", required=True, type=Path, help="path to AISHELL-3 root")
    ap.add_argument("--out", required=True, type=Path, help="output stats_zh.json path")
    ap.add_argument(
        "--ceiling",
        type=int,
        default=5500,
        choices=ceiling_selector.CEILINGS,
        help="Praat formant ceiling (Hz); pinned for every segment",
    )
    ap.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("/output/zh_phones.jsonl"),
        help="JSONL checkpoint of phoneme observations; resumable",
    )
    ap.add_argument("--n-segments", type=int, default=5000)
    # AISHELL-3 has 218 speakers (42 male + 176 female); a 3-per-speaker cap
    # would yield only 654 candidates total, far short of the 5000 target.
    # 30 per speaker × 218 = 6540 candidates → 1.5× over-sample → 5000 hits
    # the post-duration-filter target.  Per-speaker variability still gets
    # represented because the round-robin in _sample_balanced shuffles
    # speakers, not clips, before drawing.
    ap.add_argument("--max-segments-per-speaker", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--num-workers", type=int, default=1)
    ap.add_argument(
        "--aggregate-only",
        action="store_true",
        help="skip alignment, just re-aggregate the existing checkpoint",
    )
    args = ap.parse_args()

    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.aggregate_only:
        _aggregate_to_stats(args.checkpoint, args.out)
        return 0

    spk_info = parse_spk_info(args.aishell)
    transcripts = parse_content(args.aishell)
    rows = _enumerate_clips(args.aishell, spk_info, transcripts)
    logger.info(
        "enumerated %d candidate clips across %d speakers",
        len(rows),
        len({r["client_id"] for r in rows}),
    )

    # Duration filter is applied AFTER sampling — running it on all 88 k
    # AISHELL-3 clips upfront takes 10 min+ on 9P-mounted storage and most
    # of the clips never get used.  Over-sample by 1.5× to absorb the
    # ~30 % filter-out rate; final list capped at n_target.
    over_n = int(args.n_segments * 1.5)
    picked = _sample_balanced(rows, over_n, args.max_segments_per_speaker, args.seed)
    logger.info("over-sampled %d segments; running duration filter…", len(picked))
    picked = [r for r in picked if _audio_duration_ok(Path(r["audio_path"]))]
    picked = picked[: args.n_segments]
    logger.info(
        "%d segments pass duration filter [%g, %g] s (target %d)",
        len(picked),
        _MIN_DURATION_SEC,
        _MAX_DURATION_SEC,
        args.n_segments,
    )

    # Resume: skip audio_paths already in checkpoint.
    done_paths: set[str] = set()
    if args.checkpoint.exists():
        with args.checkpoint.open() as f:
            for line in f:
                try:
                    done_paths.add(json.loads(line)["__src__"])
                except (json.JSONDecodeError, KeyError):
                    continue
        logger.info("resume: %d audio paths already in checkpoint", len(done_paths))

    todo = [
        (r["audio_path"], r["sentence"], args.ceiling)
        for r in picked
        if r["audio_path"] not in done_paths
    ]
    logger.info(
        "aligning %d segments with %d worker(s) at ceiling=%d Hz",
        len(todo),
        args.num_workers,
        args.ceiling,
    )

    t0 = time.time()
    processed = 0
    failed = 0

    def _drain(audio_path: str, obs: list[dict] | None) -> None:
        nonlocal processed, failed
        if not obs:
            failed += 1
            return
        for o in obs:
            o["__src__"] = audio_path
            ckpt.write(json.dumps(o, ensure_ascii=False) + "\n")
        ckpt.flush()
        processed += 1
        if processed % 50 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (len(todo) - processed) / rate if rate > 0 else 0
            logger.info(
                "progress: %d/%d aligned, %d failed, %.1f seg/min, eta %.0f min",
                processed,
                len(todo),
                failed,
                rate * 60,
                eta / 60,
            )

    with args.checkpoint.open("a", encoding="utf-8") as ckpt:
        if args.num_workers <= 1:
            # ProcessPoolExecutor's initializer never runs in single-worker
            # mode — call it directly so _WORKER_ALIGNER is populated.
            _pool_worker_init()
            for ap_path, sent, ceil in todo:
                _drain(ap_path, _process_one(ap_path, sent, ceil))
        else:
            from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415

            with ProcessPoolExecutor(
                max_workers=args.num_workers,
                initializer=_pool_worker_init,
            ) as ex:
                for audio_path, obs in ex.map(_process_one_safe, todo, chunksize=4):
                    _drain(audio_path, obs)

    logger.info("alignment done: %d ok, %d failed in %.1fs", processed, failed, time.time() - t0)
    _aggregate_to_stats(args.checkpoint, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
