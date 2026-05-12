"""Train stats_ko.json baseline for Engine C from Common Voice ko.

Designed to run **inside the sidecar container** (where ffmpeg, sox, praat,
MFA and the korean_mfa acoustic + dictionary are baked in).  Bypasses the
HTTP ``/engine_c/analyze`` layer because before training stats_ko.json is
empty and ``resonance.compute_resonance`` would crash on ``mean([])``.

Usage (inside container):

    docker compose --profile engine-c up -d --build
    docker compose cp scripts/train_stats_ko.py visualizer-backend:/tmp/
    docker compose exec visualizer-backend python /tmp/train_stats_ko.py \\
        --corpus /mnt/cv-ko/cv-corpus-25.0-2026-XX-XX/ko \\
        --out /app/stats_ko.json \\
        --n-segments 10000

Then on host: copy /app/stats_ko.json out, commit to
voiceya/sidecars/visualizer-backend/stats_ko.json, rebuild image.

Resumable: appends one JSONL row per phoneme observation to
``--checkpoint`` (default /tmp/train_ko_phones.jsonl).  Re-running with the
same checkpoint skips any audio_path already seen and just re-aggregates.

Corpus expectations
-------------------
Common Voice ko v25 layout::

    cv-corpus-25.0-XXXX/ko/
        clips/             # *.mp3
        validated.tsv      # client_id\\tpath\\tsentence\\t...\\tgender\\t...

Filters: ``gender in {male_masculine, female_feminine}`` (CV v25 schema),
duration 5-15 s (read by librosa to skip ffmpeg roundtrip), distinct
client_id buckets so no single speaker dominates the per-phoneme stats.

Korean ASR cleanup differs from fr: we keep ONLY Hangul precomposed
syllables (U+AC00–U+D7A3) + whitespace.  Mirrors
voiceya/services/audio_analyser/engine_c_asr_ko.py::_clean_transcript and
keeps MFA from seeing any OOV tokens that the korean_mfa dict wouldn't
resolve.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import statistics
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

# This script is meant to run inside the sidecar container where /app is the
# vendored library root.  Make /app importable so we can call preprocessing
# and phones directly without going through HTTP.
sys.path.insert(0, "/app")

import acousticgender.library.phones as phones  # noqa: E402
import acousticgender.library.preprocessing as preprocessing  # noqa: E402

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("train_stats_ko")

# Common Voice v25 gender values (validated.tsv column).  Older dumps use
# "male" / "female"; v17+ uses "male_masculine" / "female_feminine".  Accept
# both so the script doesn't break on older CV releases.
_GENDER_MALE = {"male", "male_masculine"}
_GENDER_FEMALE = {"female", "female_feminine"}

_MIN_DURATION_SEC = 5.0
_MAX_DURATION_SEC = 15.0

# Per-phoneme observation gate.  Below this we won't emit the phoneme to
# stats_ko.json — resonance.compute_resonance gracefully falls back when a
# phone has no stats entry (no F_stdevs → no resonance contribution), so
# omission is safer than emitting under-sampled distributions.
_MIN_OBS_PER_PHONEME = 200


def _normalise(label: str | None) -> str | None:
	"""NFC-normalise IPA labels so length-marked vowels (eː / iː etc.) match
	across runs regardless of how Praat emits them."""
	if not label:
		return None
	return unicodedata.normalize("NFC", label)


def _sample_balanced(
	rows: list[dict],
	n_target: int,
	min_per_gender: int,
	max_per_speaker: int,
	seed: int,
) -> list[dict]:
	"""Pick up to ``n_target`` rows with both genders represented and no single
	speaker dominating.  Speakers are bucketed by ``client_id``.
	"""
	rng = random.Random(seed)
	by_speaker: dict[tuple[str, str], list[dict]] = defaultdict(list)
	for r in rows:
		by_speaker[(r["client_id"], r["gender_short"])].append(r)

	speakers_male = [k for k in by_speaker if k[1] == "male"]
	speakers_female = [k for k in by_speaker if k[1] == "female"]
	rng.shuffle(speakers_male)
	rng.shuffle(speakers_female)

	if len(speakers_male) < min_per_gender or len(speakers_female) < min_per_gender:
		logger.warning(
			"speaker pool below target: male=%d, female=%d, want >=%d each",
			len(speakers_male), len(speakers_female), min_per_gender,
		)

	picked: list[dict] = []
	pools = [iter(speakers_male), iter(speakers_female)]
	pool_idx = 0
	while len(picked) < n_target and (pools[0] or pools[1]):
		key = next(pools[pool_idx], None)
		if key is None:
			pools[pool_idx] = iter([])
			pool_idx = 1 - pool_idx
			if not any(pools):
				break
			continue
		segs = by_speaker[key][:max_per_speaker]
		picked.extend(segs)
		pool_idx = 1 - pool_idx
		if len(picked) >= n_target:
			break

	rng.shuffle(picked)
	return picked[:n_target]


def _load_corpus_index(
	corpus_dir: Path,
	max_scan_rows: int,
) -> list[dict]:
	"""Read validated.tsv and return rows that pass schema + gender filters.

	``max_scan_rows`` caps the scan so we don't read the entire TSV when we
	only want 10k segments.  CV ko v25 has ~30k validated rows total — set
	high enough to scan all of them by default.
	"""
	tsv = corpus_dir / "validated.tsv"
	clips_dir = corpus_dir / "clips"
	if not tsv.exists():
		raise FileNotFoundError(f"validated.tsv not found at {tsv}")
	if not clips_dir.is_dir():
		raise FileNotFoundError(f"clips/ not found at {clips_dir}")

	rows: list[dict] = []
	scanned = 0
	with tsv.open(encoding="utf-8") as f:
		reader = csv.DictReader(f, delimiter="\t")
		for i, row in enumerate(reader):
			if i >= max_scan_rows:
				break
			scanned = i + 1
			gender = (row.get("gender") or "").strip().lower()
			if gender in _GENDER_MALE:
				gender_short = "male"
			elif gender in _GENDER_FEMALE:
				gender_short = "female"
			else:
				continue

			path = (row.get("path") or "").strip()
			sentence = (row.get("sentence") or "").strip()
			client_id = (row.get("client_id") or "").strip()
			if not (path and sentence and client_id):
				continue

			audio_path = clips_dir / path
			if not audio_path.exists():
				continue

			rows.append({
				"client_id": client_id,
				"audio_path": str(audio_path),
				"sentence": sentence,
				"gender_short": gender_short,
			})

	logger.info("scanned %d rows; %d passed gender+path+sentence filter", scanned, len(rows))
	return rows


def _audio_duration_ok(path: str) -> bool:
	"""Cheap duration filter via librosa.get_duration (no full decode)."""
	try:
		import librosa  # noqa: PLC0415 — only needed in script
		dur = librosa.get_duration(path=path)
	except Exception as exc:
		logger.debug("duration check failed for %s: %s", path, exc)
		return False
	return _MIN_DURATION_SEC <= dur <= _MAX_DURATION_SEC


def _pool_worker_init() -> None:
	"""Give each worker its own MFA_ROOT_DIR so concurrent ``mfa align``
	subprocesses don't race in ``Archive.__init__`` → ``unpack_archive``.

	MFA extracts the acoustic-model zip into ``$MFA_ROOT_DIR/extracted_models/``
	on first use; if two workers hit this together the loser blows up with
	``FileExistsError: korean_mfa_acoustic/korean_mfa``.  Per-worker
	MFA_ROOT_DIR isolates the extraction; pretrained_models is symlinked
	from the shared cache so we don't re-download the acoustic + dict per
	worker.
	"""
	import os  # noqa: PLC0415
	pid = os.getpid()
	mfa_root = f"/tmp/mfa_worker_{pid}"
	os.makedirs(mfa_root, exist_ok=True)
	src = "/opt/mfa_root/pretrained_models"
	dst = os.path.join(mfa_root, "pretrained_models")
	if not os.path.exists(dst) and os.path.exists(src):
		os.symlink(src, dst)
	os.environ["MFA_ROOT_DIR"] = mfa_root


def _process_one_safe(args: tuple[str, str]) -> tuple[str, list[dict] | None]:
	"""Pool worker entry: ``(audio_path, sentence) → (audio_path, obs|None)``."""
	audio_path, transcript = args
	return audio_path, _process_one(audio_path, transcript)


def _process_one(audio_path: str, transcript: str) -> list[dict] | None:
	"""Run vendored MFA + Praat pipeline on one segment.  Returns list of
	{phoneme, F: [F0, F1, F2, F3]} dicts, or None on failure.

	Cleans transcript to korean_mfa dict alphabet (Hangul precomposed
	syllables only).  Mirrors voiceya/services/audio_analyser/
	engine_c_asr_ko.py::_clean_transcript for consistency.
	"""
	import re  # noqa: PLC0415
	clean_re = re.compile(r"[^가-힣\s]+")
	transcript_clean = unicodedata.normalize("NFC", transcript)
	transcript_clean = " ".join(clean_re.sub(" ", transcript_clean).split())
	if not transcript_clean:
		return None

	with open(audio_path, "rb") as f:
		audio_bytes = f.read()

	# preprocessing.process does its own mkdir(tmp_dir) — generate a unique
	# non-existent path so it can create freely.  uuid avoids the mkdtemp
	# create/rmdir dance and the race window between them.
	import uuid  # noqa: PLC0415
	tmp_dir = f"/tmp/train_ko_{uuid.uuid4().hex}"
	try:
		praat_output = preprocessing.process(audio_bytes, transcript_clean, tmp_dir, "ko")
	except Exception as exc:
		logger.debug("preprocessing.process failed: %s", exc)
		import shutil as _shutil  # noqa: PLC0415
		_shutil.rmtree(tmp_dir, ignore_errors=True)
		return None

	try:
		data = phones.parse(praat_output, "ko")
	except Exception as exc:
		logger.debug("phones.parse failed: %s", exc)
		return None

	out: list[dict] = []
	for p in data.get("phones") or []:
		phoneme = _normalise(p.get("phoneme"))
		formants = p.get("F") or []
		if not phoneme or len(formants) < 4:
			continue
		out.append({
			"phoneme": phoneme,
			"F": [float(v) if v is not None else None for v in formants[:4]],
		})
	return out


def _aggregate_to_stats(checkpoint_path: Path, out_path: Path) -> None:
	"""Read all phoneme observations from JSONL and produce stats_ko.json.

	Schema matches stats.json / stats_zh.json / stats_fr.json: ``{phoneme:
	[{mean, stdev, median, max, min}, x4]}``.  Phonemes with
	< _MIN_OBS_PER_PHONEME usable observations on either F1 or F2 are
	dropped (resonance.compute_resonance falls back gracefully to no-stats).
	"""
	by_phoneme: dict[str, list[list[float | None]]] = defaultdict(list)
	with checkpoint_path.open() as f:
		for line in f:
			row = json.loads(line)
			by_phoneme[row["phoneme"]].append(row["F"])

	stats: dict[str, list[dict]] = {}
	for phoneme, observations in by_phoneme.items():
		per_formant: list[dict | None] = []
		for i in range(4):
			values = [o[i] for o in observations if o[i] is not None]
			if len(values) < _MIN_OBS_PER_PHONEME:
				per_formant.append(None)
				continue
			per_formant.append({
				"mean":   statistics.mean(values),
				"stdev":  statistics.stdev(values) if len(values) > 1 else 0.0,
				"median": statistics.median(values),
				"max":    max(values),
				"min":    min(values),
			})
		# Require at least F1+F2 obs above gate; resonance needs both.
		if per_formant[1] is None or per_formant[2] is None:
			logger.info(
				"dropping phoneme %r: F1 obs=%d, F2 obs=%d (< %d)",
				phoneme,
				sum(1 for o in observations if o[1] is not None),
				sum(1 for o in observations if o[2] is not None),
				_MIN_OBS_PER_PHONEME,
			)
			continue
		stats[phoneme] = [
			fmt if fmt is not None else {"mean": 0.0, "stdev": 1.0, "median": 0.0, "max": 0.0, "min": 0.0}
			for fmt in per_formant
		]

	with out_path.open("w", encoding="utf-8") as f:
		json.dump(stats, f, ensure_ascii=False, indent=2)
	logger.info("wrote %s with %d phonemes", out_path, len(stats))


def main() -> int:
	parser = argparse.ArgumentParser(description="Train stats_ko.json from CV ko v25")
	parser.add_argument("--corpus", required=True, type=Path, help="path to cv-corpus-25.0-XXX/ko/")
	parser.add_argument("--out", required=True, type=Path, help="output stats_ko.json path")
	parser.add_argument(
		"--checkpoint", default=Path("/tmp/train_ko_phones.jsonl"), type=Path,
		help="JSONL of phoneme observations; resumable",
	)
	parser.add_argument("--n-segments", type=int, default=10000)
	parser.add_argument(
		"--min-speakers-per-gender", type=int, default=200,
		help="warn if below this many distinct CV speakers per gender. "
		"Default 200 (vs fr's 1000) because CV ko v25 has fewer gender-"
		"labeled speakers; raise once corpus grows.",
	)
	parser.add_argument("--max-segments-per-speaker", type=int, default=3)
	parser.add_argument("--max-scan-rows", type=int, default=200000)
	parser.add_argument("--seed", type=int, default=42)
	parser.add_argument(
		"--num-workers", type=int, default=1,
		help="parallel alignment workers (ProcessPoolExecutor). MFA + Praat are "
		"single-threaded per call; 8-16 typical on a 28-core box.",
	)
	parser.add_argument(
		"--aggregate-only", action="store_true",
		help="skip alignment; just re-aggregate the existing checkpoint",
	)
	args = parser.parse_args()

	if args.aggregate_only:
		_aggregate_to_stats(args.checkpoint, args.out)
		return 0

	rows = _load_corpus_index(args.corpus, args.max_scan_rows)
	picked = _sample_balanced(
		rows,
		args.n_segments,
		args.min_speakers_per_gender,
		args.max_segments_per_speaker,
		args.seed,
	)
	logger.info("sampled %d segments to align", len(picked))

	done_paths: set[str] = set()
	if args.checkpoint.exists():
		with args.checkpoint.open() as f:
			for line in f:
				try:
					done_paths.add(json.loads(line)["__src__"])
				except (json.JSONDecodeError, KeyError):
					continue
		logger.info("resume: %d unique audio paths already in checkpoint", len(done_paths))

	t0 = time.time()
	processed = 0
	failed = 0
	todo = [(r["audio_path"], r["sentence"]) for r in picked if r["audio_path"] not in done_paths]
	logger.info("aligning %d segments with %d worker(s)", len(todo), args.num_workers)

	def _drain(audio_path: str, obs: list[dict] | None) -> None:
		nonlocal processed, failed
		if not obs:
			failed += 1
			return
		for o in obs:
			o["__src__"] = audio_path
			ckpt.write(json.dumps(o, ensure_ascii=False) + "\n")
		ckpt.flush()
		processed += 1
		if processed % 50 == 0:
			elapsed = time.time() - t0
			rate = processed / elapsed if elapsed > 0 else 0
			logger.info(
				"progress: %d/%d aligned, %d failed, %.1f seg/min",
				processed, len(todo), failed, rate * 60,
			)

	with args.checkpoint.open("a", encoding="utf-8") as ckpt:
		if args.num_workers <= 1:
			for ap, sent in todo:
				_drain(ap, _process_one(ap, sent))
		else:
			from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415
			with ProcessPoolExecutor(
				max_workers=args.num_workers,
				initializer=_pool_worker_init,
			) as ex:
				for audio_path, obs in ex.map(_process_one_safe, todo, chunksize=4):
					_drain(audio_path, obs)

	logger.info("alignment done: %d ok, %d failed in %.1fs", processed, failed, time.time() - t0)
	_aggregate_to_stats(args.checkpoint, args.out)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
