"""Compare two stats_zh.json files side-by-side (typically 5000 Hz vs 5500 Hz).

Highlights formant-mean shifts that matter for gender-resonance scoring:
F1 (jaw openness, less ceiling-sensitive) and F2 (tongue advancement,
ceiling-sensitive — this is what the 5500 Hz training is supposed to fix).

Usage::

    python scripts/diff_stats_zh.py \\
        voiceya/sidecars/visualizer-backend/stats_zh.json \\
        ~/scratch/zh_stats_train/stats_zh_5500.json

Reports:
- coverage delta (phonemes added/dropped)
- F1/F2/F3 mean shift per phoneme (sorted by |Δ F2|)
- explicit verdict on female-/i//y//e/ F2 (the collapse canaries)
- whether F2 stdev exploded (signal of bad training data)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_F_NAMES = ["F0", "F1", "F2", "F3"]
_CANARY_VOWELS = ["i", "y", "e", "ej", "ə", "a", "u"]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("old", type=Path, help="baseline stats (typically 5000 Hz)")
    ap.add_argument("new", type=Path, help="new stats (typically 5500 Hz)")
    ap.add_argument(
        "--top", type=int, default=20, help="how many phonemes to show in the |Δ F2| table"
    )
    args = ap.parse_args()

    old = load(args.old)
    new = load(args.new)

    old_keys = set(old.keys())
    new_keys = set(new.keys())
    print("== coverage ==")
    print(f"  old: {len(old_keys)} phonemes")
    print(f"  new: {len(new_keys)} phonemes")
    print(f"  shared: {len(old_keys & new_keys)}")
    only_old = sorted(old_keys - new_keys)
    only_new = sorted(new_keys - old_keys)
    if only_old:
        print(f"  dropped (in old, not new): {only_old}")
    if only_new:
        print(f"  added   (in new, not old): {only_new}")
    print()

    # F1/F2/F3 mean shift per shared phoneme, sorted by |Δ F2|
    rows: list[dict] = []
    for phn in sorted(old_keys & new_keys):
        o = old[phn]
        n = new[phn]
        if len(o) < 4 or len(n) < 4:
            continue
        rec: dict = {"phoneme": phn}
        for i in (1, 2, 3):
            o_mean = o[i].get("mean") if isinstance(o[i], dict) else None
            n_mean = n[i].get("mean") if isinstance(n[i], dict) else None
            o_sd = o[i].get("stdev") if isinstance(o[i], dict) else None
            n_sd = n[i].get("stdev") if isinstance(n[i], dict) else None
            rec[_F_NAMES[i] + "_old"] = o_mean
            rec[_F_NAMES[i] + "_new"] = n_mean
            rec[_F_NAMES[i] + "_d"] = (
                (n_mean - o_mean) if (o_mean is not None and n_mean is not None) else None
            )
            rec[_F_NAMES[i] + "_sd_old"] = o_sd
            rec[_F_NAMES[i] + "_sd_new"] = n_sd
        rows.append(rec)

    # canary check first (the reason we did this)
    print("== F2 canary check (Mandarin female literature: i~2700 / y~2300 / e~2200) ==")
    print(f"{'phn':<6} {'F2_old':>9} {'F2_new':>9} {'ΔF2':>9} {'F2_sd_old':>11} {'F2_sd_new':>11}")
    for phn in _CANARY_VOWELS:
        if phn not in old or phn not in new:
            continue
        if len(old[phn]) < 3 or len(new[phn]) < 3:
            continue
        o2 = old[phn][2]
        n2 = new[phn][2]
        o2m = o2.get("mean") if isinstance(o2, dict) else None
        n2m = n2.get("mean") if isinstance(n2, dict) else None
        o2s = o2.get("stdev") if isinstance(o2, dict) else None
        n2s = n2.get("stdev") if isinstance(n2, dict) else None
        if None in (o2m, n2m):
            continue
        delta = n2m - o2m
        flag = "  ← canary" if phn in {"i", "y", "e"} else ""
        print(
            f"{phn:<6} {o2m:9.0f} {n2m:9.0f} {delta:+9.0f} {o2s or 0:11.0f} {n2s or 0:11.0f}{flag}"
        )
    print()

    # top-N by |Δ F2|
    rows_with_d = [r for r in rows if r.get("F2_d") is not None]
    rows_with_d.sort(key=lambda r: -abs(r["F2_d"]))
    print(f"== top {args.top} phonemes by |Δ F2| ==")
    print(
        f"{'phn':<6} {'F1_old':>9} {'F1_new':>9} {'ΔF1':>9} {'F2_old':>9} {'F2_new':>9} {'ΔF2':>9} {'F3_old':>9} {'F3_new':>9} {'ΔF3':>9}"
    )
    for r in rows_with_d[: args.top]:
        print(
            f"{r['phoneme']:<6} "
            f"{r['F1_old'] or 0:9.0f} {r['F1_new'] or 0:9.0f} {r.get('F1_d') or 0:+9.0f} "
            f"{r['F2_old']:9.0f} {r['F2_new']:9.0f} {r['F2_d']:+9.0f} "
            f"{r['F3_old'] or 0:9.0f} {r['F3_new'] or 0:9.0f} {r.get('F3_d') or 0:+9.0f}"
        )
    print()

    # stdev sanity — F2 stdev shouldn't grow dramatically (would indicate
    # the new training data is noisier than baseline)
    blowups = []
    for r in rows:
        o = r.get("F2_sd_old") or 0
        n = r.get("F2_sd_new") or 0
        if o > 0 and n / o > 1.5:
            blowups.append((r["phoneme"], o, n, n / o))
    if blowups:
        print("== F2 stdev blow-ups (new/old > 1.5×, possible noise issue) ==")
        for phn, o, n, ratio in sorted(blowups, key=lambda x: -x[3]):
            print(f"  {phn:<6} stdev: {o:.0f} → {n:.0f} ({ratio:.2f}×)")
    else:
        print("F2 stdev: no blow-ups (max growth ratio ≤ 1.5×).  Looks clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
