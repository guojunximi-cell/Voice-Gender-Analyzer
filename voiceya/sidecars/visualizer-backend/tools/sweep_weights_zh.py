#!/usr/bin/env python3
"""A/B sweep multiple weight vectors against the speaker-disjoint holdout.

Loads holdout TSVs once, then for each (label, weights) pair recomputes
``meanResonance`` per utt and reports speaker-level Δmedian + threshold-swept
accuracy.  Cheaper and more legible than calling ``validate_zh.py`` N times.

Usage::

    python tools/sweep_weights_zh.py \\
        --processed-dir /home/yaya/voiceya-baseline-zh/work/corpus-processed-zh-holdout \\
        --stats stats_zh.json \\
        --pair "EN upstream:0.732,0.268,0.0" \\
        --pair "ZH v0.1.1:0.658,0.242,0.1" \\
        --pair "ZH v0.2.1:$(cat /home/yaya/voiceya-baseline-zh/work/weights_zh.v0.2.1.json | tr -d '[]')"
"""

import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict

import numpy as np


_THIS = os.path.dirname(os.path.abspath(__file__))
_VB_ROOT = os.path.dirname(_THIS)
os.chdir(_VB_ROOT)
sys.path.insert(0, _VB_ROOT)
sys.path.insert(0, os.path.join(_VB_ROOT, "acousticgender"))


from acousticgender.library import phones, resonance  # noqa: E402


def parse_dir_name(name):
	parts = name.split("_", 3)
	if len(parts) != 4 or parts[0] not in ("m", "f"):
		return None
	gender, corpus, spk, utt = parts
	return gender, f"{corpus}:{spk}", utt


def parse_pair(s):
	if ":" not in s:
		raise ValueError(f"--pair must be 'label:w1,w2,w3' (got {s!r})")
	label, vec = s.split(":", 1)
	parts = [p for p in re.split(r"[,\s]+", vec.strip()) if p]
	if len(parts) != 3:
		raise ValueError(f"--pair vector must have 3 floats (got {vec!r})")
	return label.strip(), [float(p) for p in parts]


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--processed-dir", required=True)
	ap.add_argument("--stats", default="stats_zh.json",
	                help="copied to ./stats_zh.json (resonance.py loads that path)")
	ap.add_argument("--pair", action="append", required=True,
	                help="label:w1,w2,w3 (repeatable)")
	args = ap.parse_args()

	if args.stats != "stats_zh.json":
		import shutil
		shutil.copyfile(args.stats, "stats_zh.json")

	pairs = [parse_pair(p) for p in args.pair]

	# Phase 1: load holdout TSVs once.
	utts = []  # (gender, spk, parsed_data)
	for name in sorted(os.listdir(args.processed_dir)):
		parsed = parse_dir_name(name)
		if parsed is None:
			continue
		gender, spk, _ = parsed
		tsv = os.path.join(args.processed_dir, name, "output", "recording.tsv")
		if not os.path.exists(tsv):
			continue
		with open(tsv) as f:
			data = phones.parse(f.read(), lang="zh")
		utts.append((gender, spk, data))
	print(f"holdout utts: {len(utts)}", file=sys.stderr)

	header = f"{'weights':<14} {'med(m)':>7} {'med(f)':>7} {'Δ':>8} {'spk acc':>8}"
	print(header)
	print("-" * len(header))

	for label, w in pairs:
		spk_to_scores = defaultdict(list)
		spk_gender = {}
		skipped = 0
		for gender, spk, data in utts:
			# compute_resonance mutates data in place; make a fresh copy of phones list
			# is unnecessary because resonance only adds keys.  But do reset stdevResonance
			# isn't required; we just read meanResonance after.
			try:
				resonance.compute_resonance(data, w, lang="zh")
			except Exception:
				skipped += 1
				continue
			r = data.get("meanResonance")
			if r is None:
				skipped += 1
				continue
			spk_to_scores[spk].append(r)
			spk_gender[spk] = gender

		# spk-level median
		spk_scores = [(spk_gender[s], statistics.median(v)) for s, v in spk_to_scores.items()]
		m = [r for g, r in spk_scores if g == "m"]
		f_ = [r for g, r in spk_scores if g == "f"]
		if not m or not f_:
			print(f"{label:<14} INSUFFICIENT (m={len(m)} f={len(f_)})")
			continue
		med_m = statistics.median(m)
		med_f = statistics.median(f_)
		delta = med_f - med_m

		# threshold sweep at spk level
		all_s = np.array(m + f_)
		labels = np.array([0]*len(m) + [1]*len(f_))
		thrs = np.linspace(0, 1, 1001)
		best_acc = max(float(((all_s >= t).astype(int) == labels).mean()) for t in thrs)
		print(f"{label:<14} {med_m:>7.4f} {med_f:>7.4f} {delta:>+8.4f} {best_acc:>8.4f}"
		      + (f"  (skipped {skipped})" if skipped else ""))


if __name__ == "__main__":
	main()
