#!/usr/bin/env python3
"""Sample AISHELL-1 → corpus/{m|f}_<spk>_<utt>/ tree consumed by
acousticgender/corpusanalysis.py.

Layout expected under ``--src``::

    data_aishell/
      transcript/aishell_transcript_v0.8.txt    # <utt_id> chars
      resource_aishell/speaker.info             # <spk_id> <gender>
      wav/{train,dev,test}/<spk>/<utt>.wav

Outputs land under the same ``--out`` directory as build_zh_corpus.py with
prefix ``a1_`` — speaker IDs collide otherwise (both corpora use S####).
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _corpus_common import (
	gender_balance,
	is_holdout_speaker,
	keep_text_in_dict,
	load_mandarin_dict_chars,
	round_robin_select,
	write_manifest,
	write_utterance,
)


def parse_speaker_info(path: str) -> dict[str, str]:
	"""speaker.info: ``<spk_id> <gender>`` (one per line)."""
	out = {}
	with open(path, encoding="utf-8") as f:
		for line in f:
			parts = line.split()
			if len(parts) < 2:
				continue
			spk, gender = parts[0], parts[1]
			# Some releases prefix with 'S' already (S0002), others use bare digits.
			if not spk.startswith("S"):
				spk = "S" + spk
			g = gender.upper()
			out[spk] = "F" if g.startswith("F") else "M"
	return out


def parse_transcript(path: str) -> dict[str, str]:
	"""aishell_transcript_v0.8.txt: ``<utt_id> char1 char2 ...``."""
	out = {}
	with open(path, encoding="utf-8") as f:
		for line in f:
			parts = line.split(None, 1)
			if len(parts) != 2:
				continue
			utt, body = parts
			# body is space-separated chars; just join.
			out[utt] = body.replace(" ", "").strip()
	return out


def find_aishell1_root(src: str) -> str:
	for cand in ("data_aishell", "."):
		p = os.path.join(src, cand)
		if os.path.isdir(os.path.join(p, "transcript")):
			return p
	raise SystemExit(f"can't find data_aishell/transcript/ under {src}")


def utt_to_speaker(utt: str) -> str:
	"""AISHELL-1 utt id pattern: ``BAC009<spk>W<seq>`` (e.g. BAC009S0002W0122).
	Strip the BAC009 prefix and W## suffix to recover speaker id."""
	if utt.startswith("BAC009"):
		core = utt[6:]
	else:
		core = utt
	# split on 'W' to get the speaker portion
	spk = core.split("W")[0]
	if not spk.startswith("S"):
		spk = "S" + spk
	return spk


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--src", required=True)
	ap.add_argument("--out", required=True)
	ap.add_argument("--holdout-out", required=True)
	ap.add_argument("--dict", default=os.path.join(
		os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mandarin_dict.txt"))
	ap.add_argument("--cap-per-speaker", type=int, default=50)
	ap.add_argument("--min-chars", type=int, default=6)
	ap.add_argument("--holdout-fraction", type=float, default=0.10)
	ap.add_argument("--prefix", default="a1_")
	args = ap.parse_args()

	root = find_aishell1_root(args.src)
	print(f"AISHELL-1 root: {root}")
	os.makedirs(args.out, exist_ok=True)
	os.makedirs(args.holdout_out, exist_ok=True)

	spk_gender = parse_speaker_info(os.path.join(root, "resource_aishell", "speaker.info"))
	print(f"speakers in speaker.info: {len(spk_gender)}")

	transcripts = parse_transcript(os.path.join(root, "transcript", "aishell_transcript_v0.8.txt"))
	print(f"utterances in transcript: {len(transcripts)}")

	lex = load_mandarin_dict_chars(args.dict)

	by_train_spk: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
	by_holdout_spk: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
	missing_audio = 0
	oov_skipped = 0
	missing_spk = 0

	for utt, text in transcripts.items():
		spk = utt_to_speaker(utt)
		if spk not in spk_gender:
			missing_spk += 1
			continue
		filtered = keep_text_in_dict(text, lex, min_chars=args.min_chars)
		if filtered is None:
			oov_skipped += 1
			continue
		wav = None
		for split in ("train", "dev", "test"):
			candidate = os.path.join(root, "wav", split, spk, utt + ".wav")
			if os.path.exists(candidate):
				wav = candidate
				break
		if wav is None:
			missing_audio += 1
			continue
		dest = (by_holdout_spk if is_holdout_speaker(spk, args.holdout_fraction)
		        else by_train_spk)
		dest[spk].append((spk, utt, wav, filtered))

	print(f"oov-skipped: {oov_skipped}, missing-audio: {missing_audio}, missing-spk: {missing_spk}")
	print(f"train speakers: {len(by_train_spk)}, holdout speakers: {len(by_holdout_spk)}")

	def materialise(by_spk, out_root, label):
		labelled = {s: [(s, u, w, t) for (_, u, w, t) in items]
		            for s, items in by_spk.items()}
		picked = round_robin_select(labelled, args.cap_per_speaker)
		entries = []
		for spk, (spk2, utt, wav, text) in picked:
			gender = spk_gender[spk]
			dir_name = write_utterance(out_root, gender, spk, utt, wav, text,
			                            prefix=args.prefix)
			entries.append({"source": "aishell1", "split": label, "spk": spk,
			                "utt": utt, "gender": gender, "dir": dir_name,
			                "n_chars": len(text)})
		entries = gender_balance(entries) if label == "train" else entries
		manifest_path = os.path.join(out_root, "_manifest.json")
		# Merge with existing manifest (so AISHELL-1 + AISHELL-3 entries co-exist).
		existing = []
		if os.path.exists(manifest_path):
			import json as _json
			with open(manifest_path, encoding="utf-8") as f:
				existing = _json.load(f).get("entries", [])
		write_manifest(out_root, existing + entries)
		print(f"[{label}] wrote {len(entries)} new entries → {out_root}")
		mc = sum(1 for e in entries if e["gender"] == "M")
		fc = sum(1 for e in entries if e["gender"] == "F")
		print(f"[{label}] gender split (this corpus only): m={mc} f={fc}")

	materialise(by_train_spk, args.out, "train")
	materialise(by_holdout_spk, args.holdout_out, "holdout")


if __name__ == "__main__":
	main()
