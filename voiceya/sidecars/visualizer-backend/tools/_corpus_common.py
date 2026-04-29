"""Shared helpers for AISHELL-1/3 → corpusanalysis.py corpus assembly."""

import hashlib
import json
import os
import re
import shutil
from collections import defaultdict


HAN_RE = re.compile(r"[一-鿿]")


def load_mandarin_dict_chars(dict_path: str) -> set[str]:
	"""Return the set of single Han characters present in mandarin_mfa lexicon.

	mandarin_dict.txt rows are ``<token>\\t<probs>\\t<phonemes>``; we keep only
	rows whose token is exactly one Han char so the OOV check is character-level
	(matches preprocessing.py's ``han_chars`` segmentation).
	"""
	chars: set[str] = set()
	with open(dict_path, encoding="utf-8") as f:
		for line in f:
			tok = line.split("\t", 1)[0].strip()
			if len(tok) == 1 and HAN_RE.match(tok):
				chars.add(tok)
	return chars


def keep_text_in_dict(text: str, lexicon: set[str], min_chars: int = 4) -> str | None:
	"""Filter ``text`` to in-vocab Han characters; return joined string or None.

	Returns None when fewer than ``min_chars`` chars survive — too short to
	produce stable formant statistics after MFA alignment.
	"""
	keep = [c for c in HAN_RE.findall(text) if c in lexicon]
	if len(keep) < min_chars:
		return None
	return "".join(keep)


def is_holdout_speaker(spk_id: str, fraction: float = 0.10, seed: str = "v0.2.0") -> bool:
	"""Speaker-level deterministic split.

	Uses SHA-1(seed + spk_id) mod 1000; speakers below fraction*1000 go to
	holdout. Same seed across AISHELL-1/3 keeps the split reproducible.
	"""
	h = hashlib.sha1(f"{seed}|{spk_id}".encode()).hexdigest()
	bucket = int(h[:8], 16) % 1000
	return bucket < int(fraction * 1000)


def write_utterance(out_root: str, gender: str, spk_id: str, utt_id: str,
                    src_wav: str, transcript: str, prefix: str = "") -> str:
	"""Materialise one utterance into corpus/{m|f}_{[prefix]spk}_{utt}/.

	Writes both ``recording.wav`` (hardlink first, copy fallback) and
	``transcript.txt``. Returns the directory name for manifest tracking.
	"""
	g = "m" if gender.upper().startswith("M") else "f"
	dir_name = f"{g}_{prefix}{spk_id}_{utt_id}"
	dst_dir = os.path.join(out_root, dir_name)
	if os.path.exists(dst_dir):
		return dir_name
	os.makedirs(dst_dir, exist_ok=True)
	dst_wav = os.path.join(dst_dir, "recording.wav")
	try:
		os.link(src_wav, dst_wav)
	except OSError:
		shutil.copy2(src_wav, dst_wav)
	with open(os.path.join(dst_dir, "transcript.txt"), "w", encoding="utf-8") as f:
		f.write(transcript)
	return dir_name


def round_robin_select(by_speaker: dict[str, list], cap_per_speaker: int) -> list:
	"""Round-robin pick up to ``cap_per_speaker`` items from each speaker bucket.

	Yields items interleaved by speaker so partial runs are still gender-/spk-
	balanced. ``by_speaker`` must already be ordered (a list per speaker).
	"""
	picked = []
	pools = {s: list(items) for s, items in by_speaker.items()}
	pools = {s: items for s, items in pools.items() if items}
	while pools:
		empty = []
		for spk in list(pools.keys()):
			items = pools[spk]
			if not items:
				empty.append(spk)
				continue
			# stop pulling from a speaker that's already at cap
			if cap_per_speaker > 0:
				taken_from_spk = sum(1 for p in picked if p[0] == spk)
				if taken_from_spk >= cap_per_speaker:
					empty.append(spk)
					continue
			picked.append((spk, items.pop(0)))
		for spk in empty:
			pools.pop(spk, None)
	return picked


def write_manifest(out_root: str, entries: list[dict]) -> str:
	path = os.path.join(out_root, "_manifest.json")
	with open(path, "w", encoding="utf-8") as f:
		json.dump({"count": len(entries), "entries": entries}, f, ensure_ascii=False, indent=1)
	return path


def gender_balance(entries: list[dict]) -> list[dict]:
	"""Truncate the larger gender list to match the smaller — same policy
	corpusanalysis.py applies again at aggregation time, but doing it here too
	saves MFA wall time on imbalanced selections."""
	by_g = defaultdict(list)
	for e in entries:
		by_g[e["gender"]].append(e)
	m = by_g.get("M", []) + by_g.get("m", [])
	f = by_g.get("F", []) + by_g.get("f", [])
	n = min(len(m), len(f))
	return m[:n] + f[:n]
