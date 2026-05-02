"""Stage a balanced subset of Common Voice fr v17 to ext4.

CV fr v17 lives at /mnt/d/project_vocieduck/ablation/audio/fr/ on the host
(WSL 9P mount).  Reading 5000+ mp3s straight from /mnt/d during training
hits ~30 min IO overhead vs ext4; this one-shot stager picks the candidate
clips up front and rsyncs only what we need (~750 MB instead of ~80 GB
of the full clips dir).

Output layout under ``--out-dir`` (default ~/scratch/cv_fr_ext4/)::

    clips/                         # picked mp3s, copied verbatim
    subset.tsv                     # client_id, path, sentence, gender,
                                   #   duration_ms (subset of train.tsv)

Filters:
- gender ∈ {male_masculine, female_feminine}  (CV v17 schema; "non-binary"
  / "do_not_wish_to_say" excluded — too few samples for stable stats)
- duration ∈ [4 s, 15 s]                       (matches train_stats_zh.py)
- max ``--max-per-speaker`` segments per client_id  (avoid speaker dominance)
- balanced round-robin between male / female pools

Reusable for both audit_resonance_fr.py and train_stats_fr.py kalpy retrain.
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("stage_cv_fr")

DEFAULT_CV_ROOT = Path("/mnt/d/project_vocieduck/ablation/audio/fr")
DEFAULT_OUT = Path.home() / "scratch" / "cv_fr_ext4"

_GENDER_FEMALE = "female_feminine"
_GENDER_MALE = "male_masculine"


def load_durations(cv_root: Path) -> dict[str, int]:
    """Read clip_durations.tsv → {filename: duration_ms}."""
    out: dict[str, int] = {}
    path = cv_root / "clip_durations.tsv"
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                out[row["clip"]] = int(row["duration[ms]"])
            except (KeyError, ValueError, TypeError):
                continue
    return out


def load_manifest(cv_root: Path, durations: dict[str, int], min_ms: int, max_ms: int) -> list[dict]:
    """Filter train.tsv → rows with valid gender + duration."""
    rows: list[dict] = []
    path = cv_root / "train.tsv"
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            gender = (row.get("gender") or "").strip()
            if gender not in (_GENDER_MALE, _GENDER_FEMALE):
                continue
            clip = (row.get("path") or "").strip()
            sentence = (row.get("sentence") or "").strip()
            client_id = (row.get("client_id") or "").strip()
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


def pick_balanced(rows: list[dict], n_target: int, max_per_speaker: int, seed: int) -> list[dict]:
    """Round-robin male/female speakers; cap each speaker at max_per_speaker."""
    rng = random.Random(seed)
    by_speaker: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_speaker[(r["client_id"], r["gender"])].append(r)
    speakers_male = [k for k in by_speaker if k[1] == _GENDER_MALE]
    speakers_female = [k for k in by_speaker if k[1] == _GENDER_FEMALE]
    rng.shuffle(speakers_male)
    rng.shuffle(speakers_female)
    log.info("speaker pools: %d male, %d female", len(speakers_male), len(speakers_female))

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


def stage(picked: list[dict], cv_root: Path, out_dir: Path) -> None:
    """Copy picked mp3s + write subset.tsv to ``out_dir``.  Idempotent —
    files already present are skipped."""
    clips_src = cv_root / "clips"
    clips_dst = out_dir / "clips"
    clips_dst.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    copied = skipped = missing = 0
    for i, row in enumerate(picked, 1):
        src = clips_src / row["path"]
        dst = clips_dst / row["path"]
        if dst.exists() and dst.stat().st_size > 0:
            skipped += 1
            continue
        if not src.exists():
            missing += 1
            continue
        try:
            shutil.copy2(src, dst)
            copied += 1
        except OSError as exc:
            log.warning("copy failed %s: %s", row["path"], exc)
            missing += 1
        if i % 500 == 0:
            log.info(
                "stage %d/%d  copied=%d skipped=%d missing=%d  rate=%.1f/s",
                i,
                len(picked),
                copied,
                skipped,
                missing,
                i / (time.time() - t0),
            )

    log.info(
        "stage done: copied=%d skipped=%d missing=%d in %.1fs",
        copied,
        skipped,
        missing,
        time.time() - t0,
    )

    # Drop missing rows from the manifest so downstream readers don't trip.
    final_rows = [r for r in picked if (clips_dst / r["path"]).exists()]
    manifest_path = out_dir / "subset.tsv"
    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["client_id", "path", "sentence", "gender", "duration_ms"],
            delimiter="\t",
        )
        w.writeheader()
        w.writerows(final_rows)
    log.info("wrote %s (%d rows)", manifest_path, len(final_rows))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--cv-root", type=Path, default=DEFAULT_CV_ROOT)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--n-segments",
        type=int,
        default=7500,
        help="target candidate count; covers 5000 train + 460 audit + slack",
    )
    ap.add_argument("--max-per-speaker", type=int, default=5)
    ap.add_argument("--min-ms", type=int, default=4000)
    ap.add_argument("--max-ms", type=int, default=15000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not args.cv_root.is_dir():
        log.error("CV fr root not found: %s", args.cv_root)
        return 2

    log.info("loading clip_durations.tsv …")
    durations = load_durations(args.cv_root)
    log.info("loaded %d clip durations", len(durations))

    log.info("loading train.tsv with gender + duration filters …")
    rows = load_manifest(args.cv_root, durations, args.min_ms, args.max_ms)
    log.info(
        "%d rows pass filters [gender, %d-%d ms]",
        len(rows),
        args.min_ms,
        args.max_ms,
    )

    picked = pick_balanced(rows, args.n_segments, args.max_per_speaker, args.seed)
    log.info("picked %d clips (target %d)", len(picked), args.n_segments)

    stage(picked, args.cv_root, args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
