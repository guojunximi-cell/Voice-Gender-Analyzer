"""Engine C sidecar — thin FastAPI shell over the vendored gender-voice-
visualization pipeline (preprocessing.process → phones.parse →
resonance.compute_resonance).

Deployed as a separate container (see voiceya/sidecars/visualizer-backend.Dockerfile
and docker-compose.yml).  The voiceya worker POSTs {audio, transcript} and
receives the phone-level JSON described in pipeline.md §6.

Design notes
------------
* Working directory must be /app at startup — the vendored library reads
  stats_zh.json, weights_zh.json, mandarin_dict.txt and settings.json via
  bare relative paths.  uvicorn's CMD in the Dockerfile sets WORKDIR=/app.
* preprocessing.process() does its own shutil.rmtree(tmp_dir) on the happy
  path; the analyze endpoint adds a finally-block guard for the error path.
* Engine C is Chinese-only for this iteration (per implementation plan); we
  ignore any lang field and hard-code 'zh'.
"""

from __future__ import annotations

import json
import logging
import os
import random
import shutil
import traceback

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

import acousticgender.library.phones as phones
import acousticgender.library.preprocessing as preprocessing
import acousticgender.library.resonance as resonance
from acousticgender.library.settings import settings

logger = logging.getLogger("engine_c.sidecar")

app = FastAPI(title="voiceya Engine C sidecar", version="0.1.0")


def _load_weights() -> list[float]:
    """Load Chinese resonance weights, falling back to English if missing."""
    for candidate in ("weights_zh.json", "weights.json"):
        if os.path.exists(candidate):
            with open(candidate) as f:
                return json.load(f)
    return [0.7321428571428571, 0.26785714285714285, 0.0]


WEIGHTS: list[float] = _load_weights()
LANG = "zh"


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "weights": WEIGHTS, "lang": LANG}


@app.post("/engine_c/analyze")
async def analyze(
    audio: UploadFile = File(...),
    transcript: str = Form(...),
) -> dict:
    """Run the upstream pipeline on a single audio clip + transcript.

    Returns the `data` dict from resonance.compute_resonance, which includes:
      - words:   [{time, word, expected: [phone, ...]}]
      - phones:  [{time, phoneme, word_index, expected, F, F_stdevs, resonance?}]
      - meanPitch / medianPitch / stdevPitch
      - meanResonance / medianResonance / stdevResonance
      - mean / stdev (F-vectors)
    """
    transcript = (transcript or "").strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript is empty")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio payload is empty")

    # tmp_dir is created and torn down inside preprocessing.process.
    # The finally block also cleans up so partial dirs don't accumulate when
    # process() raises before reaching its own rmtree.
    tmp_dir = settings["recordings"] + str(random.randint(0, 2**32))

    try:
        praat_output = preprocessing.process(audio_bytes, transcript, tmp_dir, LANG)
        data = phones.parse(praat_output, LANG)
        if not data.get("phones"):
            raise RuntimeError("MFA produced no alignment output")
        resonance.compute_resonance(data, WEIGHTS, LANG)
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Engine C analyze failed: %s", exc)
        logger.debug("Engine C trace:\n%s", traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"engine_c pipeline failed: {exc}",
        ) from exc
    finally:
        # ignore_errors=True handles the case where process() already ran its
        # own rmtree on the happy path.
        shutil.rmtree(tmp_dir, ignore_errors=True)
