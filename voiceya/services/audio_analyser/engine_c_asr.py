"""Engine C ASR: FunASR Paraformer-zh → Chinese transcript.

The transcript goes to the visualizer-backend sidecar, which runs MFA on
{audio, transcript} to get phoneme alignments.  MFA is tolerant of ASR
errors (mis-transcribed characters become OOV and are skipped), so we
don't need perfect WER here — just enough to drive MFA's Viterbi.

The model is loaded lazily on first call and kept as a module-level
singleton.  If ENGINE_C_ENABLED=False, this module never imports funasr.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from io import BytesIO

import librosa

logger = logging.getLogger(__name__)

_MODEL_CACHE: object | None = None
# Serialise FunASR generate() calls — the model singleton is not thread-safe
# under concurrent asyncio.to_thread() invocations on the same worker process.
_MODEL_LOCK = threading.Lock()


def _load_model() -> object:
    """Load Paraformer-zh once per worker process.

    FunASR reads MODELSCOPE_CACHE to locate its hub — the Dockerfile bakes
    the model there at build time.  If the env var or cache is missing
    (dev/local), AutoModel falls back to an online download (slow, needs
    network).

    Must be called while holding _MODEL_LOCK.
    """
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE

    from funasr import AutoModel  # deferred — only when ENGINE_C_ENABLED

    cache = os.environ.get("MODELSCOPE_CACHE", "<unset>")
    logger.info("FunASR: loading paraformer-zh (MODELSCOPE_CACHE=%s)", cache)
    _MODEL_CACHE = AutoModel(
        model="paraformer-zh",
        disable_update=True,
        disable_log=True,
    )
    return _MODEL_CACHE


def _transcribe_sync(audio_bytes: bytes) -> str:
    """Blocking ASR — run inside asyncio.to_thread()."""
    # librosa decodes any ffmpeg-supported format; FunASR expects 16 kHz mono.
    y, _ = librosa.load(BytesIO(audio_bytes), sr=16000, mono=True)
    if len(y) == 0:
        return ""

    with _MODEL_LOCK:
        model = _load_model()
        results = model.generate(input=y, batch_size_s=60)

    if not results:
        return ""

    # FunASR returns [{'key': ..., 'text': ...}, ...].
    text = (results[0].get("text") or "").strip()
    # Paraformer sometimes emits spaces between characters — strip them so
    # MFA sees natural Chinese runs.
    return text.replace(" ", "")


async def transcribe_zh(audio_bytes: bytes) -> str:
    """Return Chinese transcript, or empty string on any failure.

    Never raises — callers use ``if not transcript: return None`` to skip
    Engine C cleanly.
    """
    if not audio_bytes:
        return ""

    try:
        return await asyncio.to_thread(_transcribe_sync, audio_bytes)
    except Exception as exc:
        logger.warning("FunASR transcribe failed: %s", exc)
        return ""
