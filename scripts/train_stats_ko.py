"""Train stats_ko.json baseline for Engine C from a Korean speech corpus.

Designed to run **inside the sidecar container** (where ffmpeg, sox, praat,
MFA and the korean_mfa acoustic + dictionary are baked in).  Bypasses the
HTTP ``/engine_c/analyze`` layer because before training stats_ko.json is
empty and ``resonance.compute_resonance`` would crash on ``mean([])``.

Supports two corpus formats:

* ``--corpus-format zeroth`` — Zeroth-Korean (OpenSLR SLR40, ~51 hr,
  105 speakers, CC BY 4.0).  Top-level ``AUDIO_INFO`` file maps
  ``SPEAKERID|NAME|SEX|SCRIPTID|DATASET`` (``m`` / ``f`` gender labels).
  Audio in ``{train,test}_data_01/<script>/<spk>/<spk>_<script>_<utt>.flac``;
  transcripts in sibling ``<spk>_<script>.trans.txt`` (one utt per line,
  space-separated ``utt_id sentence``).

* ``--corpus-format cv`` — Common Voice ko v25 (requires click-through
  download).  Reads ``validated.tsv`` with ``gender`` column filter on
  ``male_masculine`` / ``female_feminine``.  Audio in ``clips/*.mp3``.

Usage (inside container, Zeroth):

    docker compose --profile engine-c up -d --build
    # Mount the corpus (host /mnt/d/.../ko → container /mnt/ko-corpus)
    # via docker-compose.yml volumes: section
    docker compose cp scripts/train_stats_ko.py visualizer-backend:/tmp/
    docker compose exec visualizer-backend python /tmp/train_stats_ko.py \\
        --corpus-format zeroth \\
        --corpus /mnt/ko-corpus \\
        --out /app/stats_ko.json \\
        --n-segments 10000

Then on host: copy /app/stats_ko.json out, commit to
voiceya/sidecars/visualizer-backend/stats_ko.json, rebuild image.

Resumable: appends one JSONL row per phoneme observation to
``--checkpoint`` (default /tmp/train_ko_phones.jsonl).  Re-running with the
same checkpoint skips any audio_path already seen and just re-aggregates.

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


def _load_corpus_index_cv(
	corpus_dir: Path,
	max_scan_rows: int,
) -> list[dict]:
	"""Read validated.tsv (Common Voice ko) and return filtered rows.

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


def _load_corpus_index_zeroth(corpus_dir: Path) -> list[dict]:
	"""Walk Zeroth-Korean tree, join AUDIO_INFO speaker→gender, return rows.

	Zeroth-Korean layout (OpenSLR SLR40)::

	    AUDIO_INFO                        # SPEAKERID|NAME|SEX|SCRIPTID|DATASET
	    train_data_01/<script>/<spk>/<spk>_<script>_<utt>.flac
	    train_data_01/<script>/<spk>/<spk>_<script>.trans.txt    # utt_id<SP>sentence per line
	    test_data_01/...                  # same structure, smaller

	We include both train + test splits — this is a stats-only training pass
	(no held-out evaluation), so the extra speakers in test_data_01 just
	broaden the per-phoneme distribution.  Gender labels are ``m`` / ``f``
	(no inclusive enum like CV's male_masculine — the corpus pre-dates that
	convention).  Filter rejects rows whose speaker isn't gender-labeled.
	"""
	info_path = corpus_dir / "AUDIO_INFO"
	if not info_path.exists():
		raise FileNotFoundError(f"AUDIO_INFO not found at {info_path}")

	# Parse AUDIO_INFO: pipe-separated, first row is header.
	spk_gender: dict[str, str] = {}
	with info_path.open(encoding="utf-8") as f:
		for i, line in enumerate(f):
			if i == 0 or not line.strip():
				continue
			cols = line.strip().split("|")
			if len(cols) < 3:
				continue
			spk_id, _name, sex = cols[0].strip(), cols[1].strip(), cols[2].strip().lower()
			if sex == "m":
				spk_gender[spk_id] = "male"
			elif sex == "f":
				spk_gender[spk_id] = "female"

	logger.info("AUDIO_INFO: %d gender-labeled speakers", len(spk_gender))

	rows: list[dict] = []
	# Walk train_data_01/ and test_data_01/ for .trans.txt files
	for split in ("train_data_01", "test_data_01"):
		split_dir = corpus_dir / split
		if not split_dir.is_dir():
			continue
		for trans_file in split_dir.rglob("*.trans.txt"):
			# trans file lives at <split>/<script>/<spk>/<spk>_<script>.trans.txt
			spk_id = trans_file.parent.name
			gender_short = spk_gender.get(spk_id)
			if not gender_short:
				continue
			with trans_file.open(encoding="utf-8") as f:
				for line in f:
					line = line.strip()
					if not line:
						continue
					# "utt_id<SP>sentence..."
					parts = line.split(" ", 1)
					if len(parts) != 2:
						continue
					utt_id, sentence = parts
					sentence = sentence.strip()
					if not sentence:
						continue
					audio_path = trans_file.parent / f"{utt_id}.flac"
					if not audio_path.exists():
						continue
					rows.append({
						"client_id": spk_id,
						"audio_path": str(audio_path),
						"sentence": sentence,
						"gender_short": gender_short,
					})

	logger.info("Zeroth corpus: %d utterances from %d speakers (gender-labeled)",
	            len(rows), len({r["client_id"] for r in rows}))
	return rows


def _load_corpus_index(
	corpus_dir: Path,
	max_scan_rows: int,
	corpus_format: str,
) -> list[dict]:
	"""Dispatch to the right corpus reader based on --corpus-format."""
	if corpus_format == "zeroth":
		return _load_corpus_index_zeroth(corpus_dir)
	if corpus_format == "cv":
		return _load_corpus_index_cv(corpus_dir, max_scan_rows)
	raise ValueError(f"unknown corpus_format: {corpus_format}")


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
	parser = argparse.ArgumentParser(description="Train stats_ko.json from Korean speech corpus")
	parser.add_argument(
		"--corpus-format", choices=["zeroth", "cv"], default="zeroth",
		help="zeroth = OpenSLR SLR40 (Zeroth-Korean, gender-labeled, ~51 hr); "
		"cv = Common Voice ko v25 (requires manual download)",
	)
	parser.add_argument("--corpus", required=True, type=Path,
		help="corpus root: zeroth=dir with AUDIO_INFO + train/test_data_01/; "
		"cv=cv-corpus-25.0-XXX/ko/")
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

	rows = _load_corpus_index(args.corpus, args.max_scan_rows, args.corpus_format)
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
