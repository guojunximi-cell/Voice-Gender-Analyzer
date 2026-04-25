"""Engine C ASR (en-US): faster-whisper → English transcript + word timings.

Sibling of ``engine_c_asr`` (FunASR Paraformer-zh).  The en path additionally
surfaces per-word (start, end) so the sidecar can split long audio into
parallel MFA alignment chunks — zh is expected to follow once FunASR's
word-timestamp story is validated.

Returns ``(transcript, word_timestamps | None)``.  ``word_timestamps`` is a
list of ``{"word", "start", "end"}`` dicts in transcript order, with the
same letter/apostrophe cleaning as the joined transcript so indices into
``transcript.split()`` align 1:1 with ``word_timestamps`` entries.  ``None``
means the backend produced a transcript but no per-word alignment (older
faster-whisper build, degenerate audio) — caller should fall back to the
single-chunk MFA path.

Output post-processing is tuned for MFA ``english_mfa``: keep letters +
apostrophes, drop digits/punctuation so we don't feed OOV tokens to MFA.
``cmudict.txt`` stores words like ``I'M`` / ``DON'T`` — apostrophes must
survive; ``phones.py`` upper-cases each word before dictionary lookup.

Model load is lazy + singleton-per-worker; if ENGINE_C_ENABLED=False or the
request is zh-CN, faster-whisper is never imported.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
from collections import OrderedDict
from io import BytesIO

import librosa

from voiceya.config import CFG

logger = logging.getLogger(__name__)

_MODEL_CACHE: object | None = None
# faster-whisper's CTranslate2 backend is not safe across concurrent
# generate() calls on one instance; serialise like the FunASR variant.
_MODEL_LOCK = threading.Lock()

# Shares size knob with the zh cache — same rationale (identical audio bytes
# → identical transcript at temperature 0) and cheap enough to be generous.
# Stores (transcript, word_timestamps) so a cache hit also skips rebuilding
# per-word data.
_ASR_CACHE_MAX = int(os.environ.get("ENGINE_C_ASR_CACHE_SIZE", "64"))
_ASR_CACHE: OrderedDict[str, tuple[str, list[dict] | None]] = OrderedDict()
_ASR_CACHE_LOCK = threading.Lock()

# Keep ASCII letters, apostrophe, whitespace.  Everything else becomes a
# single space, then runs are collapsed — digits, punctuation, emoji,
# Chinese chars all turn into word boundaries so MFA never sees OOV tokens.
_CLEAN_RE = re.compile(r"[^A-Za-z'\s]+")


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
    """Load faster-whisper once per worker process.

    Must be called while holding _MODEL_LOCK.
    """
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE

    from faster_whisper import WhisperModel  # deferred — only when ENGINE_C_ENABLED

    model_id = CFG.engine_c_whisper_model
    device = CFG.engine_c_whisper_device
    compute_type = CFG.engine_c_whisper_compute_type
    logger.info(
        "faster-whisper: loading %s (device=%s, compute_type=%s)",
        model_id,
        device,
        compute_type,
    )
    _MODEL_CACHE = WhisperModel(model_id, device=device, compute_type=compute_type)
    return _MODEL_CACHE


def _clean_transcript(text: str) -> str:
    """Drop punctuation/digits; keep letters + apostrophes; collapse whitespace."""
    return " ".join(_CLEAN_RE.sub(" ", text).split())


def _transcribe_sync(audio_bytes: bytes) -> tuple[str, list[dict] | None]:
    """Blocking ASR — run inside asyncio.to_thread().

    Returns (transcript, word_timestamps).  word_timestamps is built by
    cleaning each whisper Word's text with _CLEAN_RE, splitting on whitespace,
    and emitting one entry per resulting token with that word's (start, end).
    The joined transcript is ``" ".join(w["word"] for w in word_timestamps)``
    so transcript.split() and word_timestamps stay in lockstep.
    """
    # librosa decodes any ffmpeg-supported format; faster-whisper accepts
    # numpy float32 arrays at 16 kHz mono directly.
    y, _ = librosa.load(BytesIO(audio_bytes), sr=16000, mono=True)
    if len(y) == 0:
        return "", None

    with _MODEL_LOCK:
        model = _load_model()
        # language="en" pins decoding so the model doesn't waste the first
        # 30 s auto-detecting (the *.en checkpoints are English-only but
        # pinning still skips the detection pass).
        # Pass through task="transcribe" (no translation) + VAD to skip the
        # long silences the upstream ffmpeg silencedetect will also mark.
        # word_timestamps=True enables cross-attention DTW alignment — cost
        # is ~0-20% on typical English speech (measured on the dev spike),
        # and the per-word (start, end) is what the sidecar chunker needs
        # to split audio + transcript for parallel MFA alignment.
        segments, _info = model.transcribe(
            y,
            language="en",
            task="transcribe",
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
        )
        # `segments` is a generator; force consumption inside the lock so
        # CTranslate2 state stays owned by this thread.  Also capture word
        # objects here for the same reason.
        raw_words: list = []
        raw_text_parts: list[str] = []
        for seg in segments:
            raw_text_parts.append(seg.text)
            for w in getattr(seg, "words", None) or []:
                raw_words.append(w)

    # Fallback path: if word_timestamps didn't surface any Word objects
    # (extremely short / silent clip, or future fw version drops them),
    # return the plain cleaned transcript and signal "no word timings".
    if not raw_words:
        return _clean_transcript(" ".join(raw_text_parts).strip()), None

    word_entries: list[dict] = []
    for w in raw_words:
        cleaned = _clean_transcript(w.word)
        if not cleaned:
            continue
        # A single whisper Word can clean+split to multiple tokens (e.g.
        # "hello—world" → ["hello", "world"] after em-dash strip).  Duplicate
        # the timestamp range across tokens so transcript.split() and
        # word_timestamps stay aligned 1:1.
        start = float(w.start)
        end = float(w.end)
        for tok in cleaned.split():
            word_entries.append({"word": tok, "start": start, "end": end})

    transcript = " ".join(e["word"] for e in word_entries)
    return transcript, word_entries or None


async def transcribe_en(audio_bytes: bytes) -> tuple[str, list[dict] | None]:
    """Return ``(transcript, word_timestamps)``.

    On failure returns ``("", None)``.  On success, ``transcript`` is the
    MFA-ready cleaned text and ``word_timestamps`` is either a list of
    ``{word, start, end}`` dicts aligned 1:1 with ``transcript.split()`` or
    ``None`` if the backend couldn't produce per-word alignment.
    """
    if not audio_bytes:
        return "", None

    key = hashlib.sha256(audio_bytes).hexdigest()
    cached = _cache_get(key)
    if cached is not None:
        text, word_ts = cached
        logger.info(
            "faster-whisper cache hit (%d chars, %s words)",
            len(text),
            len(word_ts) if word_ts else "no",
        )
        return text, word_ts

    try:
        text, word_ts = await asyncio.to_thread(_transcribe_sync, audio_bytes)
    except Exception as exc:
        logger.warning("faster-whisper transcribe failed: %s", exc)
        return "", None

    if text:
        _cache_put(key, (text, word_ts))
    return text, word_ts
