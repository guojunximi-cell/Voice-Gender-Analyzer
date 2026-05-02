"""Profile do_analyse stage timings.

Calls do_analyse directly with a fake publish() that timestamps every progress event.
Reports wall-clock seconds spent in each pct interval per audio fixture.

Usage:
    .venv/bin/python scripts/profile_pipeline.py [--no-engine-c] [--runs N]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from io import BytesIO
from pathlib import Path

import voiceya  # noqa: F401  — triggers load_config() via package __init__
from voiceya.services.audio_analyser import do_analyse  # noqa: E402
from voiceya.services.audio_analyser.seg import load_seg  # noqa: E402
from voiceya.services.sse import ProgressSSE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

FIXTURES = [
    ("zh_10s.wav", "zh-CN", "free"),
    ("zh_30s.wav", "zh-CN", "free"),
    ("zh_60s.wav", "zh-CN", "free"),
    ("female_1.wav", "zh-CN", "free"),
    ("male_1.wav", "zh-CN", "free"),
]


def _fmt_row(label, seconds, pct_from, pct_to, total):
    pct_share = (seconds / total * 100) if total else 0
    width_share = (pct_to - pct_from) if pct_to is not None else 0
    return (
        f"  {label:<28} {seconds:6.2f}s  "
        f"({pct_share:5.1f}% real | {width_share:5.1f}% bar)"
    )


async def _run_one(path: Path, language: str, mode: str):
    """Returns list[(t_seconds_from_start, pct, msg, msg_key)]."""
    events: list[tuple[float, int, str, str | None]] = []
    t0 = time.perf_counter()

    async def publish(event):
        if isinstance(event, ProgressSSE):
            events.append(
                (time.perf_counter() - t0, event.pct, event.msg, event.msg_key)
            )

    with open(path, "rb") as f:
        content = BytesIO(f.read())

    await do_analyse(content, publish, mode=mode, language=language)
    total = time.perf_counter() - t0
    return events, total


def _summarize(name, events, total):
    """Aggregate the per-pct events into named stages and print durations."""
    # Group consecutive events by their pct bucket using msg_key for clarity.
    # Track wall-clock the bar SAT at each pct.
    print(f"\n=== {name}  (total {total:.2f}s) ===")
    if not events:
        print("  (no events)")
        return None

    # Add a sentinel for the tail.
    timeline = events + [(total, 100, "done", "done")]
    stage_times: dict[str, float] = {}
    last_t = 0.0
    last_label = "boot→pct5"
    for t, pct, msg, key in timeline:
        dur = t - last_t
        stage_times[last_label] = stage_times.get(last_label, 0.0) + dur
        last_t = t
        last_label = f"pct{pct} ({key or msg[:20]})"
    # Print
    for k, v in stage_times.items():
        share = (v / total * 100) if total else 0
        print(f"  {k:<40} {v:6.2f}s  ({share:5.1f}%)")

    return stage_times


def _aggregate_runs(per_file_results):
    """Aggregate stage times across files → pct buckets."""
    # Bucket structure: {pct_bucket_label: [seconds, seconds, ...]}
    buckets: dict[str, list[float]] = {}
    for _name, stages in per_file_results:
        if stages is None:
            continue
        for k, v in stages.items():
            buckets.setdefault(k, []).append(v)
    print("\n\n=== AGGREGATE (mean across runs) ===")
    rows = []
    for k, vs in buckets.items():
        mean = sum(vs) / len(vs)
        rows.append((k, mean, len(vs)))
    # Sort by pct number when possible
    def _sort_key(r):
        s = r[0]
        if s.startswith("pct"):
            try:
                return int(s.split()[0][3:])
            except Exception:
                return 999
        return -1
    rows.sort(key=_sort_key)
    for k, mean, n in rows:
        print(f"  {k:<40} mean {mean:6.2f}s  (n={n})")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--fixture", action="append", help="filename only", default=None)
    args = ap.parse_args()

    print("[boot] loading Engine A models (one-time)…")
    t_load = time.perf_counter()
    await load_seg()
    print(f"[boot] Engine A loaded in {time.perf_counter() - t_load:.2f}s")

    fixture_dir = ROOT / "tests" / "fixtures" / "audio"
    fixtures = (
        [(name, "zh-CN", "free") for name in args.fixture]
        if args.fixture
        else FIXTURES
    )

    # ── Warmup: hit Engine C once so FunASR/MFA caches are loaded. ──
    # The very first run carries ~5-10s of cold-start cost that does not
    # repeat on subsequent calls; excluding it gives realistic numbers.
    warmup_path = fixture_dir / "zh_10s.wav"
    if warmup_path.exists():
        print("\n[warmup] one-shot zh_10s.wav to load Engine C caches…")
        t_warm = time.perf_counter()
        try:
            await _run_one(warmup_path, "zh-CN", "free")
            print(f"[warmup] done in {time.perf_counter() - t_warm:.2f}s")
        except Exception as e:
            print(f"[warmup] failed (continuing anyway): {e}")

    per_file = []
    for run_i in range(args.runs):
        print(f"\n\n##### RUN {run_i + 1}/{args.runs} #####")
        for fname, lang, mode in fixtures:
            path = fixture_dir / fname
            if not path.exists():
                print(f"  skip {fname}: not found")
                continue
            try:
                events, total = await _run_one(path, lang, mode)
                stages = _summarize(f"{fname} [{lang}/{mode}]", events, total)
                per_file.append((fname, stages))
            except Exception as e:
                import traceback

                print(f"  FAIL {fname}: {e}")
                traceback.print_exc()

    _aggregate_runs(per_file)


if __name__ == "__main__":
    asyncio.run(main())
