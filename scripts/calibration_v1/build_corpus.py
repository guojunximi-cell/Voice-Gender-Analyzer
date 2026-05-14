"""Calibration corpus v1 — build 600 stitched ~60 s clips × analyze × pack.

Goal: produce an empirical resonance% distribution per (language × gender) so
we can recalibrate the advice / How-to-use copy that today calls 50% "neutral"
when it actually sits at the female reference mean.

6 buckets × 100 utterances each, ≥100 minutes of speech per bucket:

  zh-CN  female  ← AISHELL-3 (175 F speakers available)
  zh-CN  male    ← AISHELL-3 (only 42 M speakers — multi-utt to hit 100)
  en-US  female  ← LibriSpeech train-clean-100 (125 F speakers)
  en-US  male    ← LibriSpeech train-clean-100 (126 M speakers)
  fr-FR  female  ← Common Voice fr (filter validated.tsv by gender)
  fr-FR  male    ← Common Voice fr

For each session we stitch ``clips_per_spk`` short utterances into one ~60 s
file.  The stitched wav + transcript is sent to the sidecar in **script** mode
so we skip ASR error as a variable; the engine_c JSON is then wrapped into
voiceduck's existing v1 ``.vga.json`` export schema for downstream analysis.

Layout under ``--out`` (default /mnt/d/project_vocieduck/calibration_v1/)::

    <lang>/
        manifest.jsonl                       # one row per session
        stitched/{F,M}/<spk_id>.wav          # ~60 s stitched audio
        raw/<spk_id>.json                    # sidecar /engine_c/analyze cache
        sessions/{F,M}/session_<spk_id>.vga.json  # wrapped export bundle

Usage:
    uv run python -m scripts.calibration_v1.build_corpus stage --lang zh --lang en --lang fr
    uv run python -m scripts.calibration_v1.build_corpus analyze --lang zh --lang en --lang fr
    uv run python -m scripts.calibration_v1.build_corpus pack --lang zh --lang en --lang fr

    # or run end-to-end for one language:
    uv run python -m scripts.calibration_v1.build_corpus all --lang fr
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Reuse audit_resonance_zh helpers for AISHELL-3 enumeration.  We do *not*
# import its stitch_one because we need offset support for the zh-male
# multi-session case (42 speakers × ~3 sessions = 126 → cap at 100).
from audit_resonance_zh import (  # noqa: E402
    parse_content as zh_parse_content,
)
from audit_resonance_zh import (  # noqa: E402
    parse_spk_info as zh_parse_spk_info,
)

# Reuse stage_cv_fr_subset for CV manifest parsing.
from stage_cv_fr_subset import (  # noqa: E402
    load_durations as fr_load_durations,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("calibration_v1")

# ─── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_OUT = Path("/mnt/d/project_vocieduck/calibration_v1")
DEFAULT_AISHELL = Path("/mnt/d/project_vocieduck/ablation/audio/cn/AISHELL3")
DEFAULT_LIBRISPEECH = Path("/mnt/d/project_vocieduck/ablation/audio/en/LibriSpeech")
DEFAULT_CV_FR = Path("/mnt/d/project_vocieduck/ablation/audio/fr")
DEFAULT_SIDECAR = "http://localhost:8001"
DEFAULT_TARGET_DUR_SEC = 60.0
DEFAULT_SEED = 4242

# Per-bucket session targets.  All buckets aim for 100 stitched sessions.
# zh-male only has 42 unique speakers in AISHELL-3 → multi-session per speaker
# (disjoint clip windows) to inflate to 100.  See ZH_MALE_SESSIONS_PER_SPK.
BUCKET_TARGETS = {
    ("zh-CN", "F"): 100,
    ("zh-CN", "M"): 100,
    ("en-US", "F"): 100,
    ("en-US", "M"): 100,
    ("fr-FR", "F"): 100,
    ("fr-FR", "M"): 100,
}

# How many short utts to concat per stitched session.  Tuned so each bucket
# crosses 100 minutes total (TARGET = 100 utts × 60+ s = 100+ min).  Smoke
# measurements: zh ≈ 4.7 s/clip, en ≈ 12.6 s/clip, fr ≈ 5.7 s/clip.
CLIPS_PER_SPK = {
    "zh-CN": 14,  # 14 × ~4.7 s ≈ 66 s/session → 100 × 66 s ≈ 110 min
    "en-US": 6,  # 6 × ~12.6 s ≈ 75 s/session → 100 × 75 s ≈ 125 min
    "fr-FR": 11,  # 11 × ~5.7 s ≈ 63 s/session → 100 × 63 s ≈ 105 min
}

# For zh-male we deliberately re-enter the speaker pool to inflate to 100
# sessions: 42 unique speakers × ~3 stitched sessions each (different utt
# subsets per session, deterministic via seed offset).  Documents in README.
ZH_MALE_SESSIONS_PER_SPK = 3  # 42 × 3 = 126 → cap at 100


# ─── App version (best-effort, for export bundle metadata) ────────────────
def _app_version() -> str:
    pkg_json = REPO_ROOT / "web" / "package.json"
    try:
        return json.loads(pkg_json.read_text()).get("version", "0.0.0-calibration-v1")
    except Exception:
        return "0.0.0-calibration-v1"


# ─── ffmpeg helpers ───────────────────────────────────────────────────────
def _probe_duration(wav: Path) -> float:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(wav),
            ],
            timeout=10,
        )
        return round(float(out.strip()), 3)
    except (subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _ffmpeg_concat_to_wav(src_files: list[Path], out_wav: Path) -> bool:
    """Concat audio files (any format) → 16 kHz mono PCM s16le wav."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    list_path = out_wav.with_suffix(".concat.txt")
    list_path.write_text(
        "".join(f"file '{p.absolute()}'\n" for p in src_files),
        encoding="utf-8",
    )
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(out_wav),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        return True
    except subprocess.CalledProcessError as exc:
        log.warning(
            "ffmpeg failed for %s: %s", out_wav.name, exc.stderr.decode("utf-8", "replace")[-300:]
        )
        return False
    finally:
        list_path.unlink(missing_ok=True)


# ─── Stage: zh-CN (AISHELL-3) ─────────────────────────────────────────────
def _zh_speaker_clips(
    aishell: Path,
    spk: str,
    transcripts: dict[str, str],
    *,
    want: int,
    min_clip_sec: float = 3.0,
) -> list[tuple[Path, str]]:
    """Sorted list of (wav_path, transcript) for ``spk``, up to ``want`` valid.

    Pools ``train/`` and ``test/`` since some AISHELL-3 speakers are split
    across both splits.  Stops probing as soon as ``want`` valid clips are
    found — saves ~10× ffprobe overhead at full-corpus scale.
    """
    cand: list[Path] = []
    for split in ("train", "test"):
        d = aishell / split / "wav" / spk
        if d.is_dir():
            cand.extend(d.glob("*.wav"))
    clips = sorted(p for p in cand if p.name in transcripts)
    valid: list[tuple[Path, str]] = []
    for p in clips:
        if len(valid) >= want:
            break
        dur = _probe_duration(p)
        if dur >= min_clip_sec:
            valid.append((p, transcripts[p.name]))
    return valid


def _zh_stitch_window(window: list[tuple[Path, str]], out_wav: Path) -> dict | None:
    """ffmpeg-concat the picked window of AISHELL-3 clips into one wav.

    AISHELL-3 clips are 44.1k mono 16le → -c copy is lossless concat.
    """
    if not window:
        return None
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if not (out_wav.exists() and out_wav.stat().st_size > 1024):
        list_path = out_wav.with_suffix(".concat.txt")
        list_path.write_text(
            "".join(f"file '{p.absolute()}'\n" for p, _ in window),
            encoding="utf-8",
        )
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_path),
                    "-c",
                    "copy",
                    str(out_wav),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            log.warning(
                "zh ffmpeg concat failed for %s: %s",
                out_wav.name,
                exc.stderr.decode("utf-8", "replace")[-300:],
            )
            return None
        finally:
            list_path.unlink(missing_ok=True)
    return {
        "wav": str(out_wav),
        "transcript": "".join(t for _, t in window),
        "source_clips": [p.name for p, _ in window],
        "duration_sec": _probe_duration(out_wav),
    }


def stage_zh(out_root: Path, aishell: Path, seed: int) -> list[dict]:
    """Stage zh-CN buckets.  Returns manifest rows (also written to disk)."""
    spk_info = zh_parse_spk_info(aishell)
    transcripts = zh_parse_content(aishell)

    f_speakers = sorted(s for s, m in spk_info.items() if m["gender"] == "female")
    m_speakers = sorted(s for s, m in spk_info.items() if m["gender"] == "male")
    log.info("zh: AISHELL-3 has %d F + %d M speakers", len(f_speakers), len(m_speakers))

    rng = random.Random(seed)
    rng.shuffle(f_speakers)
    rng.shuffle(m_speakers)

    rows: list[dict] = []
    stitched_root = out_root / "zh-CN" / "stitched"
    n_per_session = CLIPS_PER_SPK["zh-CN"]

    # Female: up to 100 unique speakers × 1 session each
    target_f = BUCKET_TARGETS[("zh-CN", "F")]
    picked_f = 0
    for spk in f_speakers:
        if picked_f >= target_f:
            break
        clips = _zh_speaker_clips(aishell, spk, transcripts, want=n_per_session)
        if len(clips) < n_per_session:
            continue
        session_id = spk
        out_wav = stitched_root / "F" / f"{session_id}.wav"
        row = _zh_stitch_window(clips[:n_per_session], out_wav)
        if row is None:
            continue
        row.update({"sex": "F", "lang": "zh-CN", "session_id": session_id, "spk_id": spk})
        rows.append(row)
        picked_f += 1
    log.info("zh: staged %d F sessions", picked_f)

    # Male: 42 unique speakers × multi-session (disjoint clip windows) to hit
    # the bucket target.  AISHELL-3 male speakers average ~400 clips each, so
    # 3 disjoint windows of 8 clips per speaker is comfortably within the
    # available pool.
    target_m = BUCKET_TARGETS[("zh-CN", "M")]
    want_m = n_per_session * ZH_MALE_SESSIONS_PER_SPK  # need 3 disjoint windows
    sessions_made = 0
    for cycle in range(ZH_MALE_SESSIONS_PER_SPK):
        if sessions_made >= target_m:
            break
        for spk in m_speakers:
            if sessions_made >= target_m:
                break
            clips = _zh_speaker_clips(aishell, spk, transcripts, want=want_m)
            offset = cycle * n_per_session
            window = clips[offset : offset + n_per_session]
            if len(window) < n_per_session:
                continue
            session_id = f"{spk}_s{cycle + 1}"
            out_wav = stitched_root / "M" / f"{session_id}.wav"
            row = _zh_stitch_window(window, out_wav)
            if row is None:
                continue
            row.update({"sex": "M", "lang": "zh-CN", "session_id": session_id, "spk_id": spk})
            rows.append(row)
            sessions_made += 1
    log.info(
        "zh: staged %d M sessions across %d unique speakers",
        sessions_made,
        len({r["spk_id"] for r in rows if r["sex"] == "M"}),
    )
    return rows


# ─── Stage: en-US (LibriSpeech train-clean-100) ───────────────────────────
def _libri_speakers(librispeech: Path) -> dict[str, str]:
    """Parse SPEAKERS.TXT → {spk_id: 'F'|'M'} for train-clean-100."""
    out: dict[str, str] = {}
    p = librispeech / "SPEAKERS.TXT"
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.lstrip().startswith(";"):
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 3:
            continue
        if parts[2] != "train-clean-100" or parts[1] not in ("F", "M"):
            continue
        out[parts[0]] = parts[1]
    return out


def _libri_transcript(flac: Path) -> str | None:
    parent = flac.parent
    stem = flac.stem
    try:
        spk, chap, _ = stem.split("-", 2)
    except ValueError:
        return None
    trans = parent / f"{spk}-{chap}.trans.txt"
    if not trans.is_file():
        return None
    for line in trans.read_text(encoding="utf-8", errors="replace").splitlines():
        head, _, body = line.partition(" ")
        if head == stem:
            return body.strip()
    return None


def stage_en(out_root: Path, librispeech: Path, seed: int) -> list[dict]:
    spk_sex = _libri_speakers(librispeech)
    f_speakers = sorted(s for s, x in spk_sex.items() if x == "F")
    m_speakers = sorted(s for s, x in spk_sex.items() if x == "M")
    log.info("en: LibriSpeech tcc has %d F + %d M speakers", len(f_speakers), len(m_speakers))

    rng = random.Random(seed)
    rng.shuffle(f_speakers)
    rng.shuffle(m_speakers)

    rows: list[dict] = []
    stitched_root = out_root / "en-US" / "stitched"
    subset_root = librispeech / "train-clean-100"

    for sex_label, pool, target in (
        ("F", f_speakers, BUCKET_TARGETS[("en-US", "F")]),
        ("M", m_speakers, BUCKET_TARGETS[("en-US", "M")]),
    ):
        picked = 0
        for spk in pool:
            if picked >= target:
                break
            spk_dir = subset_root / spk
            if not spk_dir.is_dir():
                continue
            flacs = sorted(spk_dir.rglob("*.flac"))
            if len(flacs) < CLIPS_PER_SPK["en-US"]:
                continue
            local_rng = random.Random(seed * 31 + hash(spk) % 1000003)
            local_rng.shuffle(flacs)

            chosen: list[Path] = []
            transcripts: list[str] = []
            for flac in flacs:
                if len(chosen) >= CLIPS_PER_SPK["en-US"]:
                    break
                tx = _libri_transcript(flac)
                if not tx:
                    continue
                chosen.append(flac)
                transcripts.append(tx)
            if len(chosen) < CLIPS_PER_SPK["en-US"]:
                continue

            session_id = f"librispeech_{spk}"
            out_wav = stitched_root / sex_label / f"{session_id}.wav"
            if out_wav.exists() and out_wav.stat().st_size > 1024:
                duration = _probe_duration(out_wav)
            else:
                if not _ffmpeg_concat_to_wav(chosen, out_wav):
                    continue
                duration = _probe_duration(out_wav)
            rows.append(
                {
                    "wav": str(out_wav),
                    "transcript": " ".join(transcripts),
                    "duration_sec": duration,
                    "source_clips": [str(p.relative_to(librispeech)) for p in chosen],
                    "sex": sex_label,
                    "lang": "en-US",
                    "session_id": session_id,
                    "spk_id": spk,
                }
            )
            picked += 1
        log.info("en: staged %d %s sessions", picked, sex_label)

    return rows


# ─── Stage: fr-FR (Common Voice fr) ───────────────────────────────────────
_FR_GENDER_F = "female_feminine"
_FR_GENDER_M = "male_masculine"


def _fr_load_validated(
    cv_root: Path, durations: dict[str, int], min_ms: int = 4000, max_ms: int = 15000
) -> list[dict]:
    """Filter validated.tsv → rows with usable gender + duration."""
    rows: list[dict] = []
    with (cv_root / "validated.tsv").open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            gender = (r.get("gender") or "").strip()
            if gender not in (_FR_GENDER_F, _FR_GENDER_M):
                continue
            clip = (r.get("path") or "").strip()
            sentence = (r.get("sentence") or "").strip()
            client_id = (r.get("client_id") or "").strip()
            if not (clip and sentence and client_id):
                continue
            dur_ms = durations.get(clip)
            if dur_ms is None or not (min_ms <= dur_ms <= max_ms):
                continue
            rows.append(
                {
                    "client_id": client_id,
                    "path": clip,
                    "sentence": sentence,
                    "gender": gender,
                    "duration_ms": dur_ms,
                }
            )
    return rows


def stage_fr(out_root: Path, cv_root: Path, seed: int) -> list[dict]:
    log.info("fr: loading clip_durations.tsv …")
    durations = fr_load_durations(cv_root)
    log.info("fr: %d clip durations loaded", len(durations))
    log.info("fr: loading validated.tsv with gender + duration filter …")
    pool = _fr_load_validated(cv_root, durations)
    log.info("fr: %d clips pass filters", len(pool))

    by_speaker: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_speaker[r["client_id"]].append(r)
    f_speakers = sorted(
        s
        for s, rs in by_speaker.items()
        if rs[0]["gender"] == _FR_GENDER_F and len(rs) >= CLIPS_PER_SPK["fr-FR"]
    )
    m_speakers = sorted(
        s
        for s, rs in by_speaker.items()
        if rs[0]["gender"] == _FR_GENDER_M and len(rs) >= CLIPS_PER_SPK["fr-FR"]
    )
    log.info(
        "fr: speaker pools (≥%d clips): %d F / %d M",
        CLIPS_PER_SPK["fr-FR"],
        len(f_speakers),
        len(m_speakers),
    )

    rng = random.Random(seed)
    rng.shuffle(f_speakers)
    rng.shuffle(m_speakers)

    rows: list[dict] = []
    stitched_root = out_root / "fr-FR" / "stitched"
    clips_dir = cv_root / "clips"

    for sex_label, pool_, target in (
        ("F", f_speakers, BUCKET_TARGETS[("fr-FR", "F")]),
        ("M", m_speakers, BUCKET_TARGETS[("fr-FR", "M")]),
    ):
        picked = 0
        for spk in pool_:
            if picked >= target:
                break
            spk_clips = by_speaker[spk][: CLIPS_PER_SPK["fr-FR"]]
            session_id = f"cv_fr_{spk[:16]}"  # truncate hash for filename sanity
            out_wav = stitched_root / sex_label / f"{session_id}.wav"
            srcs = [clips_dir / c["path"] for c in spk_clips]
            missing = [s for s in srcs if not s.exists()]
            if missing:
                log.warning("fr: speaker %s missing %d clip files; skip", spk[:8], len(missing))
                continue
            if out_wav.exists() and out_wav.stat().st_size > 1024:
                duration = _probe_duration(out_wav)
            else:
                if not _ffmpeg_concat_to_wav(srcs, out_wav):
                    continue
                duration = _probe_duration(out_wav)
            rows.append(
                {
                    "wav": str(out_wav),
                    "transcript": " ".join(c["sentence"] for c in spk_clips),
                    "duration_sec": duration,
                    "source_clips": [c["path"] for c in spk_clips],
                    "sex": sex_label,
                    "lang": "fr-FR",
                    "session_id": session_id,
                    "spk_id": spk,
                }
            )
            picked += 1
        log.info("fr: staged %d %s sessions", picked, sex_label)
    return rows


# ─── Stage dispatcher ─────────────────────────────────────────────────────
def run_stage(args: argparse.Namespace) -> int:
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    if args.limit is not None:
        for k in list(BUCKET_TARGETS):
            BUCKET_TARGETS[k] = min(BUCKET_TARGETS[k], args.limit)
        log.info("smoke limit applied: bucket caps = %s", BUCKET_TARGETS)

    rc = 0
    for lang in args.lang:
        log.info("=" * 60)
        log.info("STAGE: %s", lang)
        log.info("=" * 60)
        if lang == "zh-CN":
            rows = stage_zh(out_root, Path(args.aishell), args.seed)
        elif lang == "en-US":
            rows = stage_en(out_root, Path(args.librispeech), args.seed)
        elif lang == "fr-FR":
            rows = stage_fr(out_root, Path(args.cv_fr), args.seed)
        else:
            log.error("unknown lang: %s", lang)
            rc = 1
            continue

        manifest = out_root / lang / "manifest.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        total_dur = sum(r.get("duration_sec", 0) for r in rows)
        log.info("→ wrote %s  (%d sessions, %.1f min total)", manifest, len(rows), total_dur / 60)
    return rc


# ─── Analyze: POST each stitched wav to sidecar /engine_c/analyze ─────────
def _post_one(sidecar: str, token: str, wav: Path, transcript: str, lang: str) -> dict:
    import requests  # noqa: PLC0415

    headers = {"X-Engine-C-Token": token} if token else {}
    with wav.open("rb") as f:
        resp = requests.post(
            f"{sidecar}/engine_c/analyze",
            files={"audio": (wav.name, f, "audio/wav")},
            data={"transcript": transcript, "language": lang},
            headers=headers,
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json()


def run_analyze(args: argparse.Namespace) -> int:
    import os

    import requests  # noqa: PLC0415

    out_root = Path(args.out)

    try:
        health = requests.get(f"{args.sidecar}/healthz", timeout=10).json()
    except Exception as exc:
        log.error("sidecar unreachable at %s: %s", args.sidecar, exc)
        return 2
    log.info("sidecar healthy: %s", health)
    advertised = health.get("languages", [])

    token = os.environ.get(args.token_env, "").strip()
    rc = 0

    for lang in args.lang:
        short = lang.split("-")[0]
        if short not in advertised:
            log.warning("sidecar does not advertise %s — skip", short)
            continue
        manifest = out_root / lang / "manifest.jsonl"
        if not manifest.is_file():
            log.error("missing %s — run stage first", manifest)
            rc = 1
            continue
        rows = [json.loads(line) for line in manifest.read_text().splitlines() if line]
        raw_dir = out_root / lang / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        log.info("ANALYZE %s: %d sessions", lang, len(rows))
        t0 = time.time()
        done = skipped = failed = 0
        for i, row in enumerate(rows, 1):
            out_json = raw_dir / f"{row['session_id']}.json"
            if out_json.exists() and out_json.stat().st_size > 256:
                skipped += 1
                continue
            try:
                data = _post_one(args.sidecar, token, Path(row["wav"]), row["transcript"], lang)
            except Exception as exc:
                log.warning("[%s] %s: %s", lang, row["session_id"], str(exc)[:200])
                failed += 1
                continue
            out_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            done += 1
            if i % 10 == 0 or i == len(rows):
                elapsed = time.time() - t0
                rate = (done + 0.001) / elapsed
                eta = (len(rows) - i) / rate if rate > 0 else 0
                log.info(
                    "  %d/%d  done=%d skipped=%d failed=%d  rate=%.2f/s  eta=%.0fs",
                    i,
                    len(rows),
                    done,
                    skipped,
                    failed,
                    rate,
                    eta,
                )
        log.info(
            "%s analyze done: done=%d skipped=%d failed=%d wall=%.0fs",
            lang,
            done,
            skipped,
            failed,
            time.time() - t0,
        )
    return rc


# ─── Pack: convert raw JSON + manifest row → vga.json bundle ──────────────
def _summarize_engine_c(raw: dict, language: str, transcript: str, mode: str = "script") -> dict:
    """Transform sidecar /engine_c/analyze JSON → ``summary.engine_c`` shape.

    Replicates voiceya.services.audio_analyser.engine_c.run_engine_c by
    importing its helpers, so the resulting dict matches what the worker
    emits for the same audio + transcript pair.
    """
    from voiceya.services.audio_analyser import (  # noqa: PLC0415
        engine_c as _ec_mod,
    )
    from voiceya.services.audio_analyser import (  # noqa: PLC0415
        resonance_calibration as _rc_mod,
    )

    raw_phones = raw.get("phones") or []
    words = raw.get("words") or []
    phones = _ec_mod._build_phone_array(raw_phones, words)
    lang_short = _ec_mod._normalize_lang(language)

    silence_raw = raw.get("silenceRanges") or []
    silence_ranges: list[dict] = []
    for r in silence_raw:
        if not isinstance(r, dict):
            continue
        s = _ec_mod._safe_float(r.get("start"))
        e = _ec_mod._safe_float(r.get("end"))
        if s is not None and e is not None and e > s:
            silence_ranges.append({"start": s, "end": e})

    median_resonance = _ec_mod._safe_float(raw.get("medianResonance"))
    summary_ec = {
        "mean_pitch_hz": _ec_mod._safe_float(raw.get("meanPitch")),
        "median_pitch_hz": _ec_mod._safe_float(raw.get("medianPitch")),
        "stdev_pitch_hz": _ec_mod._safe_float(raw.get("stdevPitch")),
        "mean_resonance": _ec_mod._safe_float(raw.get("meanResonance")),
        "median_resonance": median_resonance,
        "stdev_resonance": _ec_mod._safe_float(raw.get("stdevResonance")),
        "phone_count": len(phones),
        "word_count": len(words),
        "transcript": transcript,
        "phones": phones,
        "silence_ranges": silence_ranges,
        "mode": mode,
        "script": transcript if mode == "script" else None,
        "language": language,
        # alignment_confidence wants a per-segment list to compute
        # total_audio_sec; calibration runs without Engine A so we pass 0
        # and let the helper produce a non-binding flag.
        "alignment_confidence": _ec_mod._alignment_confidence(phones, transcript, 0.0, lang_short),
        "formant_ceiling_hz": _ec_mod._safe_int(raw.get("formant_ceiling_hz")),
        "resonance_zone_key": _rc_mod.classify_zone(median_resonance, language),
        "resonance_per_vowel": _ec_mod._aggregate_per_vowel(phones, lang_short),
    }
    return summary_ec


def _build_vga_bundle(row: dict, engine_c_summary: dict, app_version: str) -> dict:
    """Wrap one engine_c summary as voiceduck v1 export schema, +calibration meta."""
    from datetime import datetime, timezone

    created_at = int(time.time() * 1000)
    summary = {
        "engine_c": engine_c_summary,
        "overall_f0_median_hz": engine_c_summary.get("median_pitch_hz"),
        "overall_pitch_mean": engine_c_summary.get("mean_pitch_hz"),
    }
    bundle = {
        "export_schema_version": "1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "ui_locale": row["lang"][:2],
        "app_version": app_version,
        "source": "vga",
        "payload": {
            "sessions": [
                {
                    "filename": Path(row["wav"]).name,
                    "summary": summary,
                    "analysis": [],
                    "created_at": created_at,
                    # audio.base64 deliberately omitted — wav lives on disk; double
                    # base64 of 600 files would balloon ~600 MB of sessions to ~2 GB
                    # of JSON for no analytical gain.
                }
            ],
        },
        "calibration_meta": {
            "lang": row["lang"],
            "sex": row["sex"],
            "spk_id": row.get("spk_id"),
            "session_id": row["session_id"],
            "duration_sec": row.get("duration_sec"),
            "source_clips": row.get("source_clips", []),
            "transcript_len_chars": len(row.get("transcript", "")),
        },
    }
    return bundle


def run_pack(args: argparse.Namespace) -> int:
    out_root = Path(args.out)
    app_v = _app_version()
    rc = 0
    for lang in args.lang:
        manifest = out_root / lang / "manifest.jsonl"
        if not manifest.is_file():
            log.error("missing %s — run stage first", manifest)
            rc = 1
            continue
        rows = [json.loads(line) for line in manifest.read_text().splitlines() if line]
        raw_dir = out_root / lang / "raw"
        sessions_root = out_root / lang / "sessions"
        packed = missing = 0
        for row in rows:
            raw = raw_dir / f"{row['session_id']}.json"
            if not raw.is_file():
                missing += 1
                continue
            raw_data = json.loads(raw.read_text(encoding="utf-8"))
            engine_c_summary = _summarize_engine_c(
                raw_data, language=lang, transcript=row.get("transcript", "")
            )
            bundle = _build_vga_bundle(row, engine_c_summary, app_v)
            sex_dir = sessions_root / row["sex"]
            sex_dir.mkdir(parents=True, exist_ok=True)
            (sex_dir / f"session_{row['session_id']}.vga.json").write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            packed += 1
        log.info("%s pack: packed=%d missing=%d", lang, packed, missing)
    return rc


# ─── CLI ──────────────────────────────────────────────────────────────────
def _add_common(p):
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--lang",
        action="append",
        choices=["zh-CN", "en-US", "fr-FR"],
        default=None,
        help="repeat per language; default = all three",
    )
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap each bucket (F and M) at N for smoke tests (default: full 100)",
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_stage = sub.add_parser("stage", help="enumerate + stitch")
    _add_common(p_stage)
    p_stage.add_argument("--aishell", type=Path, default=DEFAULT_AISHELL)
    p_stage.add_argument("--librispeech", type=Path, default=DEFAULT_LIBRISPEECH)
    p_stage.add_argument("--cv-fr", type=Path, default=DEFAULT_CV_FR)
    p_stage.set_defaults(fn=run_stage)

    p_analyze = sub.add_parser("analyze", help="POST stitched wavs to sidecar")
    _add_common(p_analyze)
    p_analyze.add_argument("--sidecar", default=DEFAULT_SIDECAR)
    p_analyze.add_argument("--token-env", default="ENGINE_C_TOKEN")
    p_analyze.set_defaults(fn=run_analyze)

    p_pack = sub.add_parser("pack", help="raw JSON + manifest → .vga.json bundles")
    _add_common(p_pack)
    p_pack.set_defaults(fn=run_pack)

    p_all = sub.add_parser("all", help="stage + analyze + pack for the given langs")
    _add_common(p_all)
    p_all.add_argument("--aishell", type=Path, default=DEFAULT_AISHELL)
    p_all.add_argument("--librispeech", type=Path, default=DEFAULT_LIBRISPEECH)
    p_all.add_argument("--cv-fr", type=Path, default=DEFAULT_CV_FR)
    p_all.add_argument("--sidecar", default=DEFAULT_SIDECAR)
    p_all.add_argument("--token-env", default="ENGINE_C_TOKEN")

    def _all(a):
        return run_stage(a) or run_analyze(a) or run_pack(a)

    p_all.set_defaults(fn=_all)

    args = ap.parse_args()
    if args.lang is None:
        args.lang = ["zh-CN", "en-US", "fr-FR"]
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
