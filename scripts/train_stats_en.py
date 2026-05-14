"""Train stats.json baseline for Engine C en-US at 5500 Hz Praat ceiling.

Background
----------
The legacy ``stats.json`` was extracted at Praat's male-default 5000 Hz
ceiling (the upstream cmudict-derived baseline shipped with
gender-voice-visualization).  ``tests/reports/calibration_v1/`` showed
the same /i/-family F2 collapse that motivated adaptive ceiling for fr
and zh — adult-female F2 of /IY/, /EY/ commonly sits at 2700-3000 Hz,
and Praat's 5-pole LPC at 5000 Hz intermittently fuses F1+F2 into a
spurious peak around 1300 Hz.  Result: en F P75 saturates at 0.987 and
26 % of LibriSpeech F speakers hit the clamp ceiling.

Re-training at 5500 Hz lifts the ceiling above the female /IY/ F2 zone
so the LPC solver stops collapsing.  Once this stats file is committed
and ``en`` is added to ``_ADAPTIVE_LANGS`` in
``wrapper/ceiling_selector.py``, the runtime selector picks 4500–6500
Hz per-recording — same protocol as zh post-2026-05-01.

Mirrors ``scripts/train_stats_zh.py`` — same kalpy ``PreloadedAligner``
+ ``ceiling_selector.rewrite_to_ceiling`` flow.  Differences vs zh:
- Corpus: LibriSpeech train-clean-100 (FLAC, ``<spk>/<chap>/``) instead
  of AISHELL-3 (WAV, ``train/wav/<spk>/``).
- Speaker→gender: ``SPEAKERS.TXT`` (pipe-separated) instead of
  ``spk-info.txt``.
- Phone label: ARPABET (IY1, AE2…) — keep stress digits to match the
  existing stats.json shape.  No tone-strip equivalent.
- MFA models: ``english_us_arpa`` acoustic + dict (matches
  ``cmudict.txt`` shipped with the sidecar).
- Audio decode: librosa for FLAC duration probe (``wave.open`` only
  handles PCM WAV).

Usage (host shell, sidecar already up)::

    docker run --rm \\
      -v /mnt/d/project_vocieduck/ablation/audio/en/LibriSpeech:/mnt/librispeech:ro \\
      -v $(pwd)/scripts:/host_scripts:ro \\
      -v $HOME/scratch/en_stats_train:/output:rw \\
      --entrypoint "" \\
      voice-gender-analyzer-visualizer-backend \\
      micromamba run -n mfa python /host_scripts/train_stats_en.py \\
        --librispeech /mnt/librispeech \\
        --subset train-clean-100 \\
        --out /output/stats_en_5500.json \\
        --ceiling 5500 \\
        --n-segments 5000 \\
        --num-workers 8

Resumable: JSONL checkpoint is appended-to per phone observation.
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
# where preprocessing / phones / settings.json / english_us_arpa live.
sys.path.insert(0, "/app")

import acousticgender.library.phones as phones  # noqa: E402
from acousticgender.library.settings import settings  # noqa: E402
from wrapper import ceiling_selector  # noqa: E402
from wrapper.preloaded_aligner import PreloadedAligner  # noqa: E402

# preprocessing.process() is the legacy subprocess-MFA path; kalpy alignment
# below replaces it entirely (~30× faster startup amortised, no spacy_pkuseg
# concurrency races).  See train_stats_zh.py preamble for full rationale.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("train_stats_en")

# LibriSpeech train-clean-100 clips are LibriVox audiobook chunks; empirical
# duration distribution (n=200 sample): p5/p50/p95 = 3.6 / 13.8 / 16.0 s,
# max 17.2 s.  Capping at 12 s (zh's choice) would reject 64 % of clips, so
# we widen to 18 s to keep effectively all of them in scope.  Praat formant
# extraction at 17 s costs ~1 s of CPU vs ~0.5 s at 8 s — proportional, no
# memory bloat (LPC is windowed).  Keep the 2.5 s floor (zh / fr both use
# it) so very-short fragments don't pollute per-phoneme stdev with noise.
_MIN_DURATION_SEC = 2.5
_MAX_DURATION_SEC = 18.0
# Per-phoneme obs gate.  English ARPABET has ~40 phones in english_us_arpa;
# 5000 segments × ~50 phones/seg → 5000-12 000 obs for common phones — well
# above 200.  Below this floor the per-formant stdev is too noisy to use as
# z-score denominator; resonance.compute_resonance falls back to no-stats
# for missing phones (graceful degradation).
_MIN_OBS_PER_PHONEME = 200

# English transcript cleanup.  LibriSpeech transcripts are uppercase with
# only letters + apostrophes (e.g. "LYNDE'S WORK"), no punctuation, no
# digits.  Lowercase for cmudict consistency (cmudict keys are uppercase
# but MFA's tokenizer normalises case) and strip anything outside the
# letter / apostrophe / hyphen / whitespace alphabet just in case.
_EN_CLEAN_RE = re.compile(r"[^A-Za-z'\-\s]+")


# ── corpus parsing ─────────────────────────────────────────────────


def parse_speakers_txt(librispeech_root: Path, subset: str) -> dict[str, dict]:
    """Parse SPEAKERS.TXT, filter to ``subset`` rows, return spk_id → {gender}.

    LibriSpeech SPEAKERS.TXT format:
        ``;ID  |SEX| SUBSET           |MINUTES| NAME``
        ``19   | F | train-clean-100  | 25.19 | Kara Shallenberg``
    """
    info_path = librispeech_root / "SPEAKERS.TXT"
    if not info_path.is_file():
        raise FileNotFoundError(f"SPEAKERS.TXT not found at {info_path}")

    out: dict[str, dict] = {}
    for line in info_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith(";"):
            continue
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 3:
            continue
        spk_id, sex, spk_subset = cols[0], cols[1], cols[2]
        if spk_subset != subset:
            continue
        if sex == "F":
            gender = "female"
        elif sex == "M":
            gender = "male"
        else:
            continue
        out[spk_id] = {"gender": gender}
    return out


def _load_chapter_transcripts(trans_path: Path) -> dict[str, str]:
    """Parse a LibriSpeech chapter ``.trans.txt`` file into utt_id → sentence.

    File format: one line per utterance, ``<utt_id> <SPACE> <SENTENCE>``.
    """
    out: dict[str, str] = {}
    for ln in trans_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        utt_id, _, sent = ln.partition(" ")
        if utt_id and sent:
            out[utt_id] = sent.strip()
    return out


def _enumerate_clips(librispeech_root: Path, subset: str, spk_info: dict[str, dict]) -> list[dict]:
    """List every FLAC under ``<subset>/<spk>/<chap>/`` whose transcript is
    in the chapter's ``.trans.txt`` and whose speaker is in ``spk_info``.

    Returns rows with ``client_id`` (spk_id), ``audio_path``, ``sentence``,
    ``gender_short`` — same shape ``train_stats_zh.py`` /
    ``train_stats_fr.py`` consume in ``_sample_balanced``.
    """
    rows: list[dict] = []
    subset_root = librispeech_root / subset
    if not subset_root.is_dir():
        raise FileNotFoundError(f"{subset} not found at {subset_root}")

    for spk_dir in subset_root.iterdir():
        if not spk_dir.is_dir():
            continue
        spk = spk_dir.name
        meta = spk_info.get(spk)
        if not meta:
            continue
        gender = meta["gender"]
        for chap_dir in spk_dir.iterdir():
            if not chap_dir.is_dir():
                continue
            trans_path = chap_dir / f"{spk}-{chap_dir.name}.trans.txt"
            if not trans_path.is_file():
                continue
            transcripts = _load_chapter_transcripts(trans_path)
            for flac in chap_dir.glob("*.flac"):
                sent = transcripts.get(flac.stem)
                if not sent:
                    continue
                rows.append(
                    {
                        "client_id": spk,
                        "audio_path": str(flac),
                        "sentence": sent,
                        "gender_short": gender,
                    }
                )
    return rows


def _sample_balanced(
    rows: list[dict], n_target: int, max_per_speaker: int, seed: int
) -> list[dict]:
    """Round-robin pick from male/female speaker buckets, capping per-speaker.

    Verbatim port of train_stats_zh.py:_sample_balanced.  LibriSpeech
    train-clean-100 has 125 F + 126 M speakers — already gender-balanced,
    so the round-robin's primary job is per-speaker capping rather than
    gender rebalancing.
    """
    rng = random.Random(seed)
    by_speaker: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_speaker[(r["client_id"], r["gender_short"])].append(r)
    speakers_male = [k for k in by_speaker if k[1] == "male"]
    speakers_female = [k for k in by_speaker if k[1] == "female"]
    rng.shuffle(speakers_male)
    rng.shuffle(speakers_female)
    logger.info("speaker pools: %d male, %d female", len(speakers_male), len(speakers_female))
    picked: list[dict] = []
    pools = [iter(speakers_male), iter(speakers_female)]
    pool_idx = 0
    while len(picked) < n_target:
        key = next(pools[pool_idx], None)
        if key is None:
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


def _audio_duration_ok(path: Path) -> bool:
    """Cheap duration filter for FLAC via librosa.get_duration (no full decode).

    librosa is already a sidecar dep (used in preprocessing).  ``wave.open``
    works for the PCM WAV that AISHELL-3 ships, but LibriSpeech is FLAC —
    librosa's soundfile backend handles FLAC natively.
    """
    try:
        import librosa  # noqa: PLC0415

        dur = librosa.get_duration(path=str(path))
    except Exception as exc:
        logger.debug("duration check failed for %s: %s", path, exc)
        return False
    return _MIN_DURATION_SEC <= dur <= _MAX_DURATION_SEC


# ── per-segment processing ─────────────────────────────────────────


# Worker-local state — populated in ``_pool_worker_init`` after fork so
# every Kaldi/lexicon object is owned by one process and never crosses the
# multiprocessing pickle boundary (none of these are picklable).
_WORKER_ALIGNER: PreloadedAligner | None = None
_WORKER_PRAAT_BIN: str | None = None
_WORKER_PRAAT_SCRIPT: str | None = None


def _process_one(audio_path: str, transcript: str, ceiling_hz: int) -> list[dict] | None:
    """Run kalpy alignment + Praat formant extraction on one FLAC, pin to
    ``ceiling_hz``, return list of {phoneme, F: [F0, F1, F2, F3]} dicts.

    Mirrors train_stats_zh.py:_process_one with two changes: en transcript
    cleanup (regex strip + lowercase) and phones.parse(..., 'en') so the
    parser uses cmudict.txt + ARPABET phone labels.
    """
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    # English transcript cleanup.  Lowercase + keep letters + apostrophes
    # + hyphens + whitespace.  LibriSpeech is already very clean (no
    # punctuation, no digits) — this is defence against future corpora.
    transcript_clean = " ".join(_EN_CLEAN_RE.sub(" ", transcript).lower().split())
    if not transcript_clean:
        return None

    aligner = _WORKER_ALIGNER
    praat_bin = _WORKER_PRAAT_BIN
    praat_script = _WORKER_PRAAT_SCRIPT
    if aligner is None or praat_bin is None or praat_script is None:
        logger.error("worker state not initialised — _pool_worker_init not run?")
        return None

    src_path = Path(audio_path)
    # PreloadedAligner.align_one writes a tempfile next to the wav; copy
    # into a per-call writable tmpdir since /mnt/librispeech is mounted
    # read-only.  Praat reads FLAC natively (libsndfile) so no transcode.
    with tempfile.TemporaryDirectory(prefix="train_en_") as tmp:
        wav_path = Path(tmp) / src_path.name
        try:
            shutil.copy2(src_path, wav_path)
        except OSError as exc:
            logger.debug("flac copy failed for %s: %s", audio_path, exc)
            return None
        grid_path = Path(tmp) / "out.TextGrid"
        try:
            aligner.align_one(wav_path, transcript_clean, grid_path)
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
        data = phones.parse(praat_raw, "en")
    except Exception as exc:
        logger.debug("phones.parse failed for %s: %s", audio_path, exc)
        return None

    out: list[dict] = []
    for p in data.get("phones") or []:
        phoneme = p.get("phoneme")
        formants = p.get("F") or []
        # Skip empty / silence labels.  english_us_arpa emits "" or "sil"
        # for inter-word silence; both should drop out of the per-phone
        # stats (we want vowel + consonant identity rows only).
        if not phoneme or phoneme in ("", "sil", "spn"):
            continue
        if len(formants) < 4:
            continue
        # ARPABET stress digits stay on the label (IY0/IY1/IY2 are
        # distinct stats.json keys in the existing baseline; preserve
        # that schema so resonance.compute_resonance's expected_key
        # lookup matches what cmudict.txt emits).
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

    Mirrors train_stats_zh.py:_pool_worker_init with:
    - english_us_arpa acoustic + dict (matches /app/cmudict.txt + the
      ARPABET phoneset the existing stats.json keys are written in).
    - PreloadedAligner.load("en", ...) — the wrapper already supports en
      (preloaded_aligner.py:31 docstring + :203 en branch).
    """
    global _WORKER_ALIGNER, _WORKER_PRAAT_BIN, _WORKER_PRAAT_SCRIPT

    # Per-worker MFA_ROOT_DIR — without this, N workers race on the
    # acoustic-model extraction directory.  See train_stats_zh.py:320 for
    # full explanation.
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

    acoustic_path = _MFA_MODEL_TYPES["acoustic"].get_pretrained_path("english_us_arpa")
    dict_path = _MFA_MODEL_TYPES["dictionary"].get_pretrained_path("english_us_arpa")
    aligner = PreloadedAligner.load("en", acoustic_path, dict_path)
    if aligner is None:
        raise RuntimeError("PreloadedAligner.load returned None for en — see logs")
    aligner.warmup()
    _WORKER_ALIGNER = aligner
    _WORKER_PRAAT_BIN = settings["praat"]
    _WORKER_PRAAT_SCRIPT = "/app/textgrid-formants.praat"
    logger.info("worker pid=%d kalpy aligner ready (en)", os.getpid())


# ── aggregation ────────────────────────────────────────────────────


def _aggregate_to_stats(checkpoint_path: Path, out_path: Path) -> None:
    """Read JSONL of phoneme observations and produce stats.json.

    Schema matches the existing stats.json: ``{phoneme: [{mean, stdev,
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
    ap = argparse.ArgumentParser(description="Train stats.json (en) at a fixed Praat ceiling")
    ap.add_argument(
        "--librispeech",
        required=True,
        type=Path,
        help="path to LibriSpeech root (containing SPEAKERS.TXT and the subset dir)",
    )
    ap.add_argument(
        "--subset",
        default="train-clean-100",
        help="LibriSpeech subset name (must match SPEAKERS.TXT SUBSET column)",
    )
    ap.add_argument("--out", required=True, type=Path, help="output stats.json path")
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
        default=Path("/output/en_phones.jsonl"),
        help="JSONL checkpoint of phoneme observations; resumable",
    )
    ap.add_argument("--n-segments", type=int, default=5000)
    # train-clean-100 has 251 speakers (125 F + 126 M); 25 per-speaker
    # cap × 251 = 6275 candidates → 1.25× over-sample buffer for the
    # 5000-segment target.  LibriSpeech sessions are long enough that we
    # could go higher, but capping at 25 keeps speaker representation
    # diverse rather than letting one chatty speaker dominate the stats.
    ap.add_argument("--max-segments-per-speaker", type=int, default=25)
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

    spk_info = parse_speakers_txt(args.librispeech, args.subset)
    rows = _enumerate_clips(args.librispeech, args.subset, spk_info)
    logger.info(
        "enumerated %d candidate clips across %d speakers",
        len(rows),
        len({r["client_id"] for r in rows}),
    )

    # Duration filter is applied AFTER sampling — running it on all
    # 28k+ LibriSpeech clips upfront takes 5+ min on /mnt-mounted
    # storage and most clips never get used.  Over-sample by 1.5× to
    # absorb the (smaller, since LibriSpeech is curated) filter-out
    # rate; final list capped at n_target.
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
