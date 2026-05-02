#!/usr/bin/env python3
"""Speaker-disjoint validator for the Chinese resonance baseline.

Inputs:
- ``--processed-dir``: output of ``corpusanalysis.py --corpus-dir holdout/
  --skip-weights`` (i.e. directory containing ``<m|f>_<prefix><spk>_<utt>/
  output/recording.tsv``).
- ``--stats``: stats_zh.json to evaluate against (either the new candidate
  or the old v0.1.1 baseline for A/B comparison).
- ``--weights``: weights_zh.json to evaluate against.

Reports speaker-level median resonance per gender, Δmedian, and best
single-threshold accuracy. Speaker-level (not utterance-level) so the
acceptance gate is honest about generalization.

Usage::

    python tools/validate_zh.py \\
        --processed-dir /home/yaya/voiceya-baseline-zh/work/corpus-processed-zh-holdout \\
        --stats stats_zh.json --weights weights_zh.json
"""

import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict


# Run from visualizer-backend/ so resonance.py finds stats_zh.json + cmudict.
_THIS = os.path.dirname(os.path.abspath(__file__))
_VB_ROOT = os.path.dirname(_THIS)
os.chdir(_VB_ROOT)
sys.path.insert(0, _VB_ROOT)
sys.path.insert(0, os.path.join(_VB_ROOT, "acousticgender"))


from acousticgender.library import phones, resonance  # noqa: E402


def parse_dir_name(name: str) -> tuple[str, str, str] | None:
	# Build/holdout corpora use ``{m|f}_{corpus_prefix}_{spk_id}_{utt_id}``
	# (e.g. ``f_a1_S0136_BAC009S0136W0121``,
	#       ``m_a3_SSB1630_SSB16300017``).  None of corpus_prefix, spk_id,
	# or utt_id contain underscores, so a 4-way split is unambiguous.
	parts = name.split("_", 3)
	if len(parts) != 4 or parts[0] not in ("m", "f"):
		return None
	gender, corpus, spk, utt = parts
	return gender, f"{corpus}:{spk}", utt


def load_weights(path: str) -> list[float]:
	with open(path) as f:
		return json.load(f)


def per_utt_resonance(tsv_path: str, weights: list[float]) -> float | None:
	# resonance.compute_resonance mutates ``data`` in place
	# (sets ``data['meanResonance']``) and returns None.
	with open(tsv_path) as f:
		tsv_text = f.read()
	data = phones.parse(tsv_text, lang="zh")
	resonance.compute_resonance(data, weights, lang="zh")
	return data.get("meanResonance")


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--processed-dir", required=True,
	                help="dir with <m|f>_<spk>_<utt>/output/recording.tsv")
	ap.add_argument("--stats", default="stats_zh.json", help="stats file resonance.py will load")
	ap.add_argument("--weights", default="weights_zh.json", help="weights file to evaluate")
	ap.add_argument("--report-out", default=None, help="optional JSON report path")
	ap.add_argument("--threshold-resolution", type=int, default=1001)
	args = ap.parse_args()

	if args.stats != "stats_zh.json":
		# resonance.py opens 'stats_zh.json' verbatim → swap by symlink/copy
		import shutil
		shutil.copyfile(args.stats, "stats_zh.json")

	weights = load_weights(args.weights)
	print(f"weights: {weights}")
	print(f"processed-dir: {args.processed_dir}")

	utt_resonance = []  # (gender, spk_id, value)
	skipped = 0
	for name in sorted(os.listdir(args.processed_dir)):
		parsed = parse_dir_name(name)
		if parsed is None:
			continue
		gender, spk_id, utt = parsed
		tsv = os.path.join(args.processed_dir, name, "output", "recording.tsv")
		if not os.path.exists(tsv):
			skipped += 1
			continue
		try:
			r = per_utt_resonance(tsv, weights)
		except Exception as exc:
			print(f"  skip {name}: {exc}", file=sys.stderr)
			skipped += 1
			continue
		if r is None:
			skipped += 1
			continue
		utt_resonance.append((gender, spk_id, r))

	print(f"valid utterances: {len(utt_resonance)} (skipped {skipped})")
	if not utt_resonance:
		raise SystemExit("no utterances scored — nothing to validate")

	# Speaker-level: median of utterance resonance per speaker.
	by_spk: dict[tuple[str, str], list[float]] = defaultdict(list)
	for gender, spk, r in utt_resonance:
		by_spk[(gender, spk)].append(r)

	spk_scores = [(g, s, statistics.median(vals)) for (g, s), vals in by_spk.items()]
	m_scores = [r for g, _, r in spk_scores if g == "m"]
	f_scores = [r for g, _, r in spk_scores if g == "f"]
	print(f"speakers: m={len(m_scores)} f={len(f_scores)}")

	median_m = statistics.median(m_scores) if m_scores else float("nan")
	median_f = statistics.median(f_scores) if f_scores else float("nan")
	delta = median_f - median_m
	print(f"median(m)={median_m:.4f}  median(f)={median_f:.4f}  Δ={delta:+.4f}")

	# Threshold sweep on speaker-level scores.
	import numpy as np
	all_scores = np.array(m_scores + f_scores)
	labels = np.array([0] * len(m_scores) + [1] * len(f_scores))  # 0=m, 1=f
	thresholds = np.linspace(0.0, 1.0, args.threshold_resolution)
	best_thr, best_acc = 0.5, 0.0
	for thr in thresholds:
		pred = (all_scores >= thr).astype(int)
		acc = float((pred == labels).mean())
		if acc > best_acc:
			best_acc, best_thr = acc, float(thr)
	print(f"speaker-level best acc={best_acc:.4f} at thr={best_thr:.4f}")

	report = {
		"weights": weights,
		"n_utts": len(utt_resonance),
		"n_speakers_m": len(m_scores),
		"n_speakers_f": len(f_scores),
		"median_m": median_m,
		"median_f": median_f,
		"delta": delta,
		"speaker_level_acc": best_acc,
		"speaker_level_threshold": best_thr,
		"per_speaker": [
			{"gender": g, "spk": s, "median_resonance": r}
			for g, s, r in sorted(spk_scores)
		],
	}
	if args.report_out:
		with open(args.report_out, "w") as f:
			json.dump(report, f, ensure_ascii=False, indent=1)
		print(f"wrote {args.report_out}")

	# Acceptance gate (informational; caller decides).
	gate_delta_ok = delta >= 0.18
	gate_acc_ok = best_acc >= 0.85
	gate_pass = gate_delta_ok and gate_acc_ok
	print(f"gate: Δ≥0.18={'✓' if gate_delta_ok else '✗'}  acc≥0.85={'✓' if gate_acc_ok else '✗'}  → {'PASS' if gate_pass else 'FAIL'}")


if __name__ == "__main__":
	main()
