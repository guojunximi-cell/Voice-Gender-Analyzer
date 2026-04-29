#!/usr/bin/env python3
"""Sample AISHELL-3 → corpus/{m|f}_<spk>_<utt>/ tree consumed by
acousticgender/corpusanalysis.py.

Layout expected under ``--src``::

    data_aishell3/
      spk-info.txt              # SPKID Age Gender Accent
      train/
        content.txt             # <utt>.wav<TAB>char1 pinyin1 char2 pinyin2 ...
        wav/<spk>/<utt>.wav
      test/
        content.txt
        wav/<spk>/<utt>.wav

Example::

    python tools/build_zh_corpus.py \\
        --src /home/yaya/voiceya-baseline-zh/corpus-src/aishell3 \\
        --out /home/yaya/voiceya-baseline-zh/work/corpus \\
        --holdout-out /home/yaya/voiceya-baseline-zh/work/holdout \\
        --cap-per-speaker 50
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


def parse_spk_info(path: str) -> dict[str, str]:
	"""Returns {spk_id: 'M'|'F'}; AISHELL-3 reports 'male'/'female'."""
	out = {}
	with open(path, encoding="utf-8") as f:
		for line in f:
			line = line.strip()
			if not line or line.startswith("//") or line.startswith("#"):
				continue
			parts = line.split()
			if len(parts) < 3:
				continue
			spk, _age, gender = parts[0], parts[1], parts[2]
			g = gender.lower()
			out[spk] = "F" if g.startswith("f") else "M"
	return out


def parse_content(path: str) -> dict[str, str]:
	"""content.txt has '<utt>.wav<TAB>char1 pinyin1 char2 pinyin2 ...'.

	We keep only the characters; pinyin is dropped. preprocessing.process()
	will run a Han-char regex anyway, so feeding raw mixed text is harmless,
	but stripping pinyin here keeps the manifest readable.
	"""
	out = {}
	with open(path, encoding="utf-8") as f:
		for line in f:
			line = line.rstrip("\n")
			if not line:
				continue
			if "\t" in line:
				utt_wav, body = line.split("\t", 1)
			else:
				parts = line.split(None, 1)
				if len(parts) != 2:
					continue
				utt_wav, body = parts
			utt = utt_wav[:-4] if utt_wav.endswith(".wav") else utt_wav
			tokens = body.split()
			# even-indexed tokens are characters, odd-indexed are pinyin in
			# AISHELL-3; if format differs (some lines have only chars), the
			# Han filter downstream still works.
			chars = "".join(tokens[::2])
			out[utt] = chars
	return out


def find_aishell3_root(src: str) -> str:
	"""Tolerate both ``<src>/data_aishell3/...`` and ``<src>/...`` layouts."""
	if os.path.isdir(os.path.join(src, "data_aishell3")):
		return os.path.join(src, "data_aishell3")
	if os.path.isfile(os.path.join(src, "spk-info.txt")):
		return src
	raise SystemExit(f"can't find spk-info.txt under {src}")


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--src", required=True, help="dir containing data_aishell3/")
	ap.add_argument("--out", required=True, help="training corpus root")
	ap.add_argument("--holdout-out", required=True, help="speaker-disjoint holdout root")
	ap.add_argument("--dict", default=os.path.join(
		os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mandarin_dict.txt"),
		help="mandarin_dict.txt for OOV pre-filter")
	ap.add_argument("--cap-per-speaker", type=int, default=50)
	ap.add_argument("--min-chars", type=int, default=6)
	ap.add_argument("--holdout-fraction", type=float, default=0.10)
	ap.add_argument("--prefix", default="a3_", help="filename prefix to disambiguate from AISHELL-1")
	args = ap.parse_args()

	root = find_aishell3_root(args.src)
	print(f"AISHELL-3 root: {root}")
	os.makedirs(args.out, exist_ok=True)
	os.makedirs(args.holdout_out, exist_ok=True)

	spk_gender = parse_spk_info(os.path.join(root, "spk-info.txt"))
	print(f"speakers in spk-info.txt: {len(spk_gender)}")

	content: dict[str, str] = {}
	for split in ("train", "test"):
		p = os.path.join(root, split, "content.txt")
		if os.path.exists(p):
			content.update(parse_content(p))
	print(f"utterances in content.txt: {len(content)}")

	lex = load_mandarin_dict_chars(args.dict)
	print(f"in-dict Han chars: {len(lex)}")

	# Group candidate utterances by speaker, applying the OOV pre-filter.
	by_train_spk: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
	by_holdout_spk: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
	missing_audio = 0
	oov_skipped = 0

	for utt, text in content.items():
		# AISHELL-3 utt id starts with the speaker id (first 7 chars: e.g. SSB0005).
		spk = utt[:7]
		if spk not in spk_gender:
			continue
		filtered = keep_text_in_dict(text, lex, min_chars=args.min_chars)
		if filtered is None:
			oov_skipped += 1
			continue
		# Audio path: train/wav/<spk>/<utt>.wav (test mirrors layout)
		wav = None
		for split in ("train", "test"):
			candidate = os.path.join(root, split, "wav", spk, utt + ".wav")
			if os.path.exists(candidate):
				wav = candidate
				break
		if wav is None:
			missing_audio += 1
			continue
		dest = (by_holdout_spk if is_holdout_speaker(spk, args.holdout_fraction)
		        else by_train_spk)
		dest[spk].append((spk, utt, wav, filtered))

	print(f"oov-skipped: {oov_skipped}, missing-audio: {missing_audio}")
	print(f"train speakers: {len(by_train_spk)}, holdout speakers: {len(by_holdout_spk)}")

	def materialise(by_spk, out_root, label):
		# attach gender to the round-robin tuples
		labelled = {s: [(s, u, w, t) for (_, u, w, t) in items]
		            for s, items in by_spk.items()}
		picked = round_robin_select(labelled, args.cap_per_speaker)
		entries = []
		for spk, (spk2, utt, wav, text) in picked:
			gender = spk_gender[spk]
			dir_name = write_utterance(out_root, gender, spk, utt, wav, text,
			                            prefix=args.prefix)
			entries.append({"source": "aishell3", "split": label, "spk": spk,
			                "utt": utt, "gender": gender, "dir": dir_name,
			                "n_chars": len(text)})
		entries = gender_balance(entries) if label == "train" else entries
		write_manifest(out_root, entries)
		print(f"[{label}] wrote {len(entries)} entries → {out_root}")
		# count by gender
		mc = sum(1 for e in entries if e["gender"] == "M")
		fc = sum(1 for e in entries if e["gender"] == "F")
		print(f"[{label}] gender split: m={mc} f={fc}")

	materialise(by_train_spk, args.out, "train")
	materialise(by_holdout_spk, args.holdout_out, "holdout")


if __name__ == "__main__":
	main()
