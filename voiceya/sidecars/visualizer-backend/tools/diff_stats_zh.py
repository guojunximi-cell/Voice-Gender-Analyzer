#!/usr/bin/env python3
"""Side-by-side diff of two stats_zh.json baselines.

Usage::

    python tools/diff_stats_zh.py stats_zh.v0.1.1.json stats_zh.json
"""

import json
import sys


F_LABEL = ["F0", "F1", "F2", "F3"]


def load(path: str) -> dict:
	with open(path) as f:
		return json.load(f)


def main() -> None:
	if len(sys.argv) != 3:
		raise SystemExit(__doc__)
	old = load(sys.argv[1])
	new = load(sys.argv[2])

	old_keys = set(old)
	new_keys = set(new)
	added = sorted(new_keys - old_keys)
	dropped = sorted(old_keys - new_keys)
	common = sorted(old_keys & new_keys)

	print(f"phones: old={len(old_keys)} new={len(new_keys)} "
	      f"added={len(added)} dropped={len(dropped)}")
	if added:
		print(f"  added: {added}")
	if dropped:
		print(f"  dropped: {dropped}")

	# Per-phone shift table: |Δmean| / stdev_old, sorted descending.
	rows = []
	for ph in common:
		for i in range(4):
			old_m = old[ph][i]["mean"]
			new_m = new[ph][i]["mean"]
			old_s = old[ph][i]["stdev"] or 1.0
			rows.append((abs(new_m - old_m) / old_s, ph, F_LABEL[i],
			             old_m, new_m, old_s, new[ph][i]["stdev"]))
	rows.sort(reverse=True)

	print("\ntop 15 mean shifts (|Δmean| / stdev_old):")
	print(f"  {'phone':>6} {'F':<3} {'old_mean':>10} {'new_mean':>10} "
	      f"{'old_stdev':>10} {'new_stdev':>10} {'shift':>6}")
	for shift, ph, fi, om, nm, os_, ns in rows[:15]:
		print(f"  {ph:>6} {fi:<3} {om:>10.2f} {nm:>10.2f} {os_:>10.2f} {ns:>10.2f} {shift:>6.2f}")

	# Average shift
	mean_shift = sum(r[0] for r in rows) / max(1, len(rows))
	print(f"\nmean |Δmean|/stdev_old over {len(rows)} (phone,F) cells: {mean_shift:.3f}")


if __name__ == "__main__":
	main()
