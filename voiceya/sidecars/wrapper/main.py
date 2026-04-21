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

import hmac
import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import traceback

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

import acousticgender.library.phones as phones
import acousticgender.library.preprocessing as preprocessing
import acousticgender.library.resonance as resonance
from acousticgender.library.settings import settings

logger = logging.getLogger("engine_c.sidecar")

app = FastAPI(title="voiceya Engine C sidecar", version="0.1.0")

# ── Security knobs (env-driven so the vendored library stays untouched) ──
# H2: per-request audio size cap.  Defends the sidecar against unbounded
# uploads if it's ever exposed beyond the docker-compose internal network.
# Default 50 MiB is generous vs. the worker's MAX_FILE_SIZE_MB (10) so a
# legitimate worker request always fits.
MAX_AUDIO_BYTES = int(os.environ.get("ENGINE_C_MAX_AUDIO_MB", "50")) * 1024 * 1024
# H2: shared-secret bearer token between worker and sidecar.  Empty string
# means auth disabled (dev / single-tenant docker network); a startup warning
# is emitted in that case so the operator notices.  When set, requests must
# carry a matching X-Engine-C-Token header (compared in constant time).
EXPECTED_TOKEN = os.environ.get("ENGINE_C_TOKEN", "").strip()
if not EXPECTED_TOKEN:
    logger.warning(
        "ENGINE_C_TOKEN not set — sidecar accepting unauthenticated requests. "
        "Set the env var on both worker (ENGINE_C_SIDECAR_TOKEN) and sidecar "
        "(ENGINE_C_TOKEN) to enable shared-secret auth."
    )


def _check_auth(token_header: str | None) -> None:
    """Constant-time token check; no-op when EXPECTED_TOKEN is unset."""
    if not EXPECTED_TOKEN:
        return
    if not token_header or not hmac.compare_digest(token_header, EXPECTED_TOKEN):
        raise HTTPException(status_code=401, detail="invalid or missing engine_c token")


def _load_weights() -> list[float]:
    """Load Chinese resonance weights, falling back to English if missing."""
    for candidate in ("weights_zh.json", "weights.json"):
        if os.path.exists(candidate):
            with open(candidate) as f:
                return json.load(f)
    return [0.7321428571428571, 0.26785714285714285, 0.0]


WEIGHTS: list[float] = _load_weights()
LANG = "zh"

# ── MFA fast-mode patch ──────────────────────────────────────────────
# Vendored preprocessing.py:119-125 calls MFA with `--clean --beam 100
# --retry_beam 400`.  `--clean` wipes MFA's acoustic-model cache on *every*
# request so each run pays the 10-30 s cold-boot cost of reloading the
# Mandarin model.  Dropping `--clean` is correctness-neutral — MFA's default
# cache behavior is "reuse across runs" — but stays within upstream's exact
# beam widths, so alignment quality on noisy / accented speech is unchanged.
#
# We can't edit the vendored file (upstream sync policy — see
# voiceya/sidecars/README.md), so we rebind the `subprocess` name inside
# preprocessing's namespace to a shim that rewrites the MFA align args on
# the fly.  The shim delegates every other attribute (STDOUT, Popen, …) and
# every non-MFA `check_output` call to the real subprocess module, so the
# noise-reduction / resample / Praat subprocess calls are untouched.
#
# Opt-out: set ENGINE_C_FAST_MFA=0 to run upstream's original args verbatim.
_FAST_MFA = os.environ.get("ENGINE_C_FAST_MFA", "1").lower() in ("1", "true", "yes", "on")


def _looks_like_mfa_align(args: object) -> bool:
    # preprocessing.py passes args as a plain list; first element is either
    # the mfa shell shim path (Linux/macOS) or [python, mfa-script.py]
    # (Windows).  "align" is always the immediate positional after the
    # executable on both platforms — keep detection cheap + explicit.
    if not isinstance(args, (list, tuple)):
        return False
    return "align" in args and "--beam" in args


def _tune_mfa_args(args: list) -> list:
    tuned = [a for a in args if a != "--clean"]
    return tuned


if _FAST_MFA:
    import types as _types

    _real_subprocess = preprocessing.subprocess
    _real_check_output = _real_subprocess.check_output

    def _patched_check_output(cmd, *a, **kw):
        if _looks_like_mfa_align(cmd):
            cmd = _tune_mfa_args(list(cmd))
        return _real_check_output(cmd, *a, **kw)

    # Lightweight namespace that proxies every attribute of the real
    # subprocess module except check_output.  Scoped to preprocessing's
    # module globals only — the rest of the process (wrapper, uvicorn,
    # FastAPI, future maintainers) sees the unmodified subprocess module.
    _sp_shim = _types.SimpleNamespace()
    for _name in dir(_real_subprocess):
        if not _name.startswith("_"):
            setattr(_sp_shim, _name, getattr(_real_subprocess, _name))
    _sp_shim.check_output = _patched_check_output
    preprocessing.subprocess = _sp_shim

    logger.info("Engine C: MFA fast-mode enabled (--clean dropped; beams kept at upstream).")

# ── Silence detection ───────────────────────────────────────────────
# The vendored preprocessing.process() already runs ffmpeg silencedetect
# internally (for noise-profile extraction) but discards the ranges.  We
# re-run it here so the wrapper owns the signal without having to patch the
# vendored library.  Cost: ~100-300 ms of extra ffmpeg on the request path,
# trivial next to MFA alignment.
#
# Thresholds match preprocessing.py:30 (-30 dB, min 0.5 s) so the ranges
# returned here line up with what process() uses internally.  These also
# match the frontend's mental model: any pause the user hears as a sentence
# boundary will exceed 0.5 s at conversational speech levels.
_SILENCE_RE = re.compile(r"silence_(start|end):\s*(-?[\d.]+)")


def _detect_silence(
    audio_bytes: bytes,
    threshold_db: int = -30,
    min_dur_sec: float = 0.5,
) -> list[dict[str, float]]:
    """Return [{start, end}] silence intervals via ffmpeg silencedetect.

    Defensive: never raises — returns `[]` on any failure (ffmpeg missing,
    decode error, timeout).  Caller treats empty list as "no info" and falls
    back to the phone-gap heuristic.
    """
    if not audio_bytes:
        return []
    tmp_path: str | None = None
    try:
        # delete=False + manual unlink so ffmpeg (separate process) can open
        # the file on OSes where NamedTemporaryFile holds an exclusive lock.
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        proc = subprocess.run(  # noqa: S603 — args are hard-coded, no shell
            [
                settings["ffmpeg"],
                "-nostats",
                "-i",
                tmp_path,
                "-af",
                f"silencedetect=n={threshold_db}dB:d={min_dur_sec}",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("silencedetect failed: %s", exc)
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    starts: list[float] = []
    ends: list[float] = []
    for line in (proc.stderr or "").splitlines():
        m = _SILENCE_RE.search(line)
        if not m:
            continue
        try:
            val = float(m.group(2))
        except ValueError:
            continue
        (starts if m.group(1) == "start" else ends).append(val)

    # Pair each start with the first end that comes after it.  Handles the
    # normal case (balanced pairs) plus edge cases: audio starts in silence
    # (stray leading end → dropped) or ends in silence (trailing start with
    # no end → dropped).  Downstream only trusts closed intervals.
    pairs: list[dict[str, float]] = []
    end_idx = 0
    for s in starts:
        while end_idx < len(ends) and ends[end_idx] <= s:
            end_idx += 1
        if end_idx >= len(ends):
            break
        pairs.append({"start": round(s, 3), "end": round(ends[end_idx], 3)})
        end_idx += 1
    return pairs


@app.get("/healthz")
def healthz() -> dict:
    # M2: don't surface internal config (weights, lang) on an unauthenticated
    # endpoint.  Health checks only need a 200 + minimal body.
    return {"ok": True}


@app.post("/engine_c/analyze")
async def analyze(
    audio: UploadFile = File(...),
    transcript: str = Form(...),
    x_engine_c_token: str | None = Header(default=None, alias="X-Engine-C-Token"),
) -> dict:
    """Run the upstream pipeline on a single audio clip + transcript.

    Returns the `data` dict from resonance.compute_resonance, which includes:
      - words:   [{time, word, expected: [phone, ...]}]
      - phones:  [{time, phoneme, word_index, expected, F, F_stdevs, resonance?}]
      - meanPitch / medianPitch / stdevPitch
      - meanResonance / medianResonance / stdevResonance
      - mean / stdev (F-vectors)
    """
    _check_auth(x_engine_c_token)

    transcript = (transcript or "").strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript is empty")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio payload is empty")
    # H2: refuse oversized payloads after the read finishes.  UploadFile
    # already buffered the body; a streaming-size check would need rewriting
    # against the raw request, which is overkill for this internal endpoint
    # — but at least we bound memory + downstream subprocess work.
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"audio payload exceeds {MAX_AUDIO_BYTES // (1024 * 1024)} MiB limit",
        )

    # tmp_dir is created and torn down inside preprocessing.process.
    # The finally block also cleans up so partial dirs don't accumulate when
    # process() raises before reaching its own rmtree.
    tmp_dir = settings["recordings"] + str(random.randint(0, 2**32))

    # Snapshot cwd so we can restore it in the finally block.  The vendored
    # preprocessing.process() does `os.chdir(tmp_dir)` before MFA but only
    # restores on the success path — if MFA raises, cwd stays inside tmp_dir,
    # then our finally rmtree's tmp_dir, leaving the process with a cwd
    # pointing at a deleted directory.  Subsequent requests then crash at
    # `os.getcwd()` inside preprocessing.process with a bare Errno-2 (no
    # path), which is opaque and looks unrelated to the original failure.
    try:
        saved_cwd = os.getcwd()
    except OSError:
        # Already poisoned by a prior request — bail to /app (set by the
        # sidecar Dockerfile WORKDIR) so we have a known-good cwd.
        saved_cwd = "/app"
        os.chdir(saved_cwd)

    try:
        # Run silencedetect alongside the main pipeline.  Independent of MFA,
        # so even if alignment fails we'd still have the ranges — but we
        # only reach the return on full success anyway, so we compute it
        # here to keep the happy path linear.
        silence_ranges = _detect_silence(audio_bytes)

        praat_output = preprocessing.process(audio_bytes, transcript, tmp_dir, LANG)
        data = phones.parse(praat_output, LANG)
        if not data.get("phones"):
            raise RuntimeError("MFA produced no alignment output")
        resonance.compute_resonance(data, WEIGHTS, LANG)
        data["silenceRanges"] = silence_ranges
        return data
    except HTTPException:
        raise
    except Exception as exc:
        # H1: never echo the internal exception text to the client — MFA
        # stderr / file paths / command lines used to leak via `detail`.
        # Full traceback stays in server logs for ops.
        logger.warning("Engine C analyze failed: %s", exc)
        logger.warning("Engine C trace:\n%s", traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail="engine_c pipeline failed",
        ) from exc
    finally:
        # ignore_errors=True handles the case where process() already ran its
        # own rmtree on the happy path.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # Restore cwd in case the vendored preprocessing.process chdir'd
        # into tmp_dir and raised before restoring (see saved_cwd note above).
        try:
            if os.getcwd() != saved_cwd:
                os.chdir(saved_cwd)
        except OSError:
            os.chdir(saved_cwd)
