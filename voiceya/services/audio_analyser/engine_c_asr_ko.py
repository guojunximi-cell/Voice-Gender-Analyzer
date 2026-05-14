"""Engine C ASR (ko-KR): faster-whisper multilingual → Korean transcript + word timings.

Sibling of ``engine_c_asr_fr`` (French faster-whisper).  The ko path uses a
multilingual checkpoint (``*.en`` checkpoints can't decode Korean), pins
``language="ko"`` to skip auto-detection, and preserves Hangul syllables for
MFA ``korean_mfa`` dictionary lookups.

Returns ``(transcript, word_timestamps | None)`` — same contract as the en/fr
siblings so the sidecar's chunker path is reused unchanged.

Output post-processing for MFA ``korean_mfa``: keep Hangul precomposed
syllables (U+AC00–U+D7A3) + whitespace; drop Latin / digits / punctuation
so MFA never sees OOV tokens.  Hangul Jamo (U+1100–U+11FF, U+3130–U+318F)
also dropped — modern orthography is precomposed-only, and the
``korean_mfa_dict.txt`` keys are precomposed.  No case-folding (Hangul is
caseless).  NFC-normalise to keep composed syllables intact regardless of
how Whisper emitted them.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import unicodedata
from collections import OrderedDict
from io import BytesIO

import librosa

from voiceya.config import CFG

logger = logging.getLogger(__name__)

_MODEL_CACHE: object | None = None
_MODEL_LOCK = threading.Lock()

_ASR_CACHE_MAX = int(os.environ.get("ENGINE_C_ASR_CACHE_SIZE", "64"))
_ASR_CACHE: OrderedDict[str, tuple[str, list[dict] | None]] = OrderedDict()
_ASR_CACHE_LOCK = threading.Lock()

# Keep Hangul precomposed syllable block (U+AC00–U+D7A3) + whitespace only.
# Everything else (digits, Latin, punctuation, Jamo, em-dash, emoji, CJK)
# collapses to a single space so MFA never sees OOV.  korean_mfa_dict.txt
# is keyed on precomposed Hangul, so any Latin loanwords ("스마트폰" is fine
# because it's Hangul; "smartphone" would be OOV) get dropped at source.
_CLEAN_RE = re.compile(r"[^가-힣\s]+")


def _cache_get(key: str) -> tuple[str, list[dict] | None] | None:
	with _ASR_CACHE_LOCK:
		if key not in _ASR_CACHE:
			return None
		_ASR_CACHE.move_to_end(key)
		return _ASR_CACHE[key]


def _cache_put(key: str, value: tuple[str, list[dict] | None]) -> None:
	if _ASR_CACHE_MAX <= 0:
		return
	with _ASR_CACHE_LOCK:
		_ASR_CACHE[key] = value
		_ASR_CACHE.move_to_end(key)
		while len(_ASR_CACHE) > _ASR_CACHE_MAX:
			_ASR_CACHE.popitem(last=False)


def _load_model() -> object:
	"""Load faster-whisper once per worker process. Caller holds _MODEL_LOCK."""
	global _MODEL_CACHE
	if _MODEL_CACHE is not None:
		return _MODEL_CACHE

	from faster_whisper import WhisperModel  # noqa: PLC0415 — deferred when feature off

	model_id = CFG.engine_c_whisper_model_ko
	device = CFG.engine_c_whisper_device
	compute_type = CFG.engine_c_whisper_compute_type
	logger.info(
		"faster-whisper (ko): loading %s (device=%s, compute_type=%s)",
		model_id,
		device,
		compute_type,
	)
	_MODEL_CACHE = WhisperModel(model_id, device=device, compute_type=compute_type)
	return _MODEL_CACHE


def _clean_transcript(text: str) -> str:
	"""Drop non-Hangul; collapse whitespace.  NFC-normalise so precomposed
	syllables match the korean_mfa dict's encoding regardless of how Whisper
	emitted them.
	"""
	normalised = unicodedata.normalize("NFC", text)
	return " ".join(_CLEAN_RE.sub(" ", normalised).split())


def _transcribe_sync(audio_bytes: bytes) -> tuple[str, list[dict] | None]:
	"""Blocking ASR — run inside asyncio.to_thread()."""
	y, _ = librosa.load(BytesIO(audio_bytes), sr=16000, mono=True)
	if len(y) == 0:
		return "", None

	with _MODEL_LOCK:
		model = _load_model()
		# language="ko" pins decoding so the multilingual model doesn't waste
		# the first 30 s auto-detecting.  word_timestamps=True powers the
		# sidecar's parallel-chunking path same as en/fr.
		segments, _info = model.transcribe(
			y,
			language="ko",
			task="transcribe",
			beam_size=5,
			vad_filter=True,
			word_timestamps=True,
		)
		raw_words: list = []
		raw_text_parts: list[str] = []
		for seg in segments:
			raw_text_parts.append(seg.text)
			for w in getattr(seg, "words", None) or []:
				raw_words.append(w)

	if not raw_words:
		return _clean_transcript(" ".join(raw_text_parts).strip()), None

	word_entries: list[dict] = []
	for w in raw_words:
		cleaned = _clean_transcript(w.word)
		if not cleaned:
			continue
		start = float(w.start)
		end = float(w.end)
		for tok in cleaned.split():
			word_entries.append({"word": tok, "start": start, "end": end})

	transcript = " ".join(e["word"] for e in word_entries)
	return transcript, word_entries or None


async def transcribe_ko(audio_bytes: bytes) -> tuple[str, list[dict] | None]:
	"""Return ``(transcript, word_timestamps)``; ``("", None)`` on failure."""
	if not audio_bytes:
		return "", None

	key = hashlib.sha256(audio_bytes).hexdigest()
	cached = _cache_get(key)
	if cached is not None:
		text, word_ts = cached
		# 命中事件保留 INFO；字符/词数是用户转写指纹，下放 DEBUG。
		logger.info("faster-whisper (ko) cache hit")
		logger.debug(
			"faster-whisper (ko) cache hit (%d chars, %s words)",
			len(text),
			len(word_ts) if word_ts else "no",
		)
		return text, word_ts

	try:
		text, word_ts = await asyncio.to_thread(_transcribe_sync, audio_bytes)
	except Exception as exc:
		logger.warning("faster-whisper (ko) transcribe failed: %s", exc)
		return "", None

	if text:
		_cache_put(key, (text, word_ts))
	return text, word_ts
