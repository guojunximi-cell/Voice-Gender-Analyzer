"""Engine C ASR (en-US): faster-whisper → English transcript.

Sibling of ``engine_c_asr`` (FunASR Paraformer-zh) — same contract
(``transcribe_en(audio_bytes) -> str``) so ``run_engine_c`` can swap based on
the request language without caring about backend differences.

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
_ASR_CACHE_MAX = int(os.environ.get("ENGINE_C_ASR_CACHE_SIZE", "64"))
_ASR_CACHE: OrderedDict[str, str] = OrderedDict()
_ASR_CACHE_LOCK = threading.Lock()

# Keep ASCII letters, apostrophe, whitespace.  Everything else becomes a
# single space, then runs are collapsed — digits, punctuation, emoji,
# Chinese chars all turn into word boundaries so MFA never sees OOV tokens.
_CLEAN_RE = re.compile(r"[^A-Za-z'\s]+")


def _cache_get(key: str) -> str | None:
    with _ASR_CACHE_LOCK:
        if key not in _ASR_CACHE:
            return None
        _ASR_CACHE.move_to_end(key)
        return _ASR_CACHE[key]


def _cache_put(key: str, value: str) -> None:
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


def _transcribe_sync(audio_bytes: bytes) -> str:
    """Blocking ASR — run inside asyncio.to_thread()."""
    # librosa decodes any ffmpeg-supported format; faster-whisper accepts
    # numpy float32 arrays at 16 kHz mono directly.
    y, _ = librosa.load(BytesIO(audio_bytes), sr=16000, mono=True)
    if len(y) == 0:
        return ""

    with _MODEL_LOCK:
        model = _load_model()
        # language="en" pins decoding so the model doesn't waste the first
        # 30 s auto-detecting (the *.en checkpoints are English-only but
        # pinning still skips the detection pass).
        # Pass through task="transcribe" (no translation) + VAD to skip the
        # long silences the upstream ffmpeg silencedetect will also mark.
        segments, _info = model.transcribe(
            y,
            language="en",
            task="transcribe",
            beam_size=5,
            vad_filter=True,
        )
        # `segments` is a generator; force consumption inside the lock so
        # CTranslate2 state stays owned by this thread.
        raw = " ".join(seg.text for seg in segments).strip()

    return _clean_transcript(raw)


async def transcribe_en(audio_bytes: bytes) -> str:
    """Return English transcript (lowercase-free, apostrophe-safe), or "" on failure."""
    if not audio_bytes:
        return ""

    key = hashlib.sha256(audio_bytes).hexdigest()
    cached = _cache_get(key)
    if cached is not None:
        logger.info("faster-whisper cache hit (%d chars)", len(cached))
        return cached

    try:
        text = await asyncio.to_thread(_transcribe_sync, audio_bytes)
    except Exception as exc:
        logger.warning("faster-whisper transcribe failed: %s", exc)
        return ""

    if text:
        _cache_put(key, text)
    return text
