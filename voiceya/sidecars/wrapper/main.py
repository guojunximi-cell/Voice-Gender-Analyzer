"""Engine C sidecar — thin FastAPI shell over the vendored gender-voice-
visualization pipeline (preprocessing.process → phones.parse →
resonance.compute_resonance).

Deployed as a separate container (see voiceya/sidecars/visualizer-backend.Dockerfile
and docker-compose.yml).  The voiceya worker POSTs {audio, transcript} and
receives the phone-level JSON described in pipeline.md §6.

Design notes
------------
* Working directory must be /app at startup — the vendored library reads
  stats_{zh,en}.json, weights_{zh,en}.json, mandarin_dict.txt / cmudict.txt
  and settings.json via bare relative paths.  uvicorn's CMD in the
  Dockerfile sets WORKDIR=/app.
* preprocessing.process() does its own shutil.rmtree(tmp_dir) on the happy
  path; the analyze endpoint adds a finally-block guard for the error path.
* Per-request `language` form field (zh-CN / en-US) picks the asset set;
  default is zh-CN so existing worker clients without a language field keep
  working.  Unsupported languages → 422.
"""

from __future__ import annotations

import asyncio
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


# ── Language routing ─────────────────────────────────────────────────
# Request-level `language` (zh-CN / en-US) → short code (zh / en) → asset
# set.  The vendored library already branches on `lang` internally (see
# acousticgender/library/preprocessing.py, phones.py, resonance.py), so the
# wrapper just needs to validate + route.
_LANG_ALIASES: dict[str, str] = {
    "zh": "zh",
    "zh-cn": "zh",
    "zh_cn": "zh",
    "cmn": "zh",
    "mandarin": "zh",
    "en": "en",
    "en-us": "en",
    "en_us": "en",
    "english": "en",
}
_LANG_WEIGHTS_FILE: dict[str, str] = {"zh": "weights_zh.json", "en": "weights.json"}
_LANG_STATS_FILE: dict[str, str] = {"zh": "stats_zh.json", "en": "stats.json"}
_LANG_DICT_FILE: dict[str, str] = {"zh": "mandarin_dict.txt", "en": "cmudict.txt"}


def _normalize_lang(raw: str | None) -> str:
    """Map `zh-CN` / `en-US` / etc. → short code; returns "" when invalid."""
    if not raw:
        return ""
    return _LANG_ALIASES.get(raw.strip().lower(), "")


def _load_weights(lang: str) -> list[float]:
    """Load resonance weights for `lang`; raises FileNotFoundError if missing."""
    path = _LANG_WEIGHTS_FILE[lang]
    with open(path) as f:
        return json.load(f)


def _lang_available(lang: str) -> bool:
    """True iff every asset required by the vendored pipeline exists on disk."""
    return all(
        os.path.exists(p)
        for p in (_LANG_WEIGHTS_FILE[lang], _LANG_STATS_FILE[lang], _LANG_DICT_FILE[lang])
    )


_SUPPORTED_LANGS: list[str] = [lang for lang in ("zh", "en") if _lang_available(lang)]
_WEIGHTS_BY_LANG: dict[str, list[float]] = {lang: _load_weights(lang) for lang in _SUPPORTED_LANGS}
if not _SUPPORTED_LANGS:
    logger.error(
        "Engine C sidecar started but no language assets are available. "
        "Expected stats_zh.json+weights_zh.json+mandarin_dict.txt or "
        "stats.json+weights.json+cmudict.txt under %s.",
        os.getcwd(),
    )

# ── MFA fast-mode patch ──────────────────────────────────────────────
# Vendored preprocessing.py:119-125 calls MFA with `--clean --beam 100
# --retry_beam 400`.  We rewrite this to narrow the beams for speed:
#   * `--beam` 100 → 50 (env: ENGINE_C_MFA_BEAM)
#   * `--retry_beam` 400 → 200 (env: ENGINE_C_MFA_RETRY_BEAM)
# Upstream chose wide values for noisy/accented speech; our inputs are
# mostly clean studio-ish voice samples, so a 2× shrink is usually safe.
# MFA falls back to `--retry_beam` automatically when the initial pass
# fails, so correctness degrades gracefully rather than losing frames.
#
# `--clean` is KEPT.  MFA keys its per-corpus session directory on the
# *corpus folder name* (`corpus` every run for us), and without `--clean`
# MFA tries to reuse references from the previous request's tmp_dir,
# which we rm -rf'd in our finally block → FileNotFoundError on the 2nd+
# request.  An earlier commit (9799fa0) dropped `--clean` believing it
# wiped the acoustic-model cache; it does not — that cache lives at
# ~/Documents/MFA/pretrained_models/ and is orthogonal.  Keeping `--clean`
# is a correctness requirement, not a perf choice.
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
_MFA_BEAM = os.environ.get("ENGINE_C_MFA_BEAM", "50").strip()
_MFA_RETRY_BEAM = os.environ.get("ENGINE_C_MFA_RETRY_BEAM", "200").strip()


def _looks_like_mfa_align(args: object) -> bool:
    # preprocessing.py passes args as a plain list; first element is either
    # the mfa shell shim path (Linux/macOS) or [python, mfa-script.py]
    # (Windows).  "align" is always the immediate positional after the
    # executable on both platforms — keep detection cheap + explicit.
    if not isinstance(args, (list, tuple)):
        return False
    return "align" in args and "--beam" in args


# Vendored preprocessing.py:87 hardcodes `english_mfa` for non-zh requests,
# but that model outputs IPA — incompatible with the ARPABET stats.json and
# cmudict.txt this sidecar ships.  `english_us_arpa` is the ARPABET sibling,
# same MFA v2+ generation.  Swap it at subprocess-invocation time so the
# vendored source stays pristine (CLAUDE.md §2 / sidecars/README.md policy).
_ENGLISH_MODEL_MAP: dict[str, str] = {"english_mfa": "english_us_arpa"}


def _tune_mfa_args(args: list) -> list:
    out: list = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--beam" and i + 1 < len(args) and _MFA_BEAM:
            out.extend(["--beam", _MFA_BEAM])
            i += 2
            continue
        if tok == "--retry_beam" and i + 1 < len(args) and _MFA_RETRY_BEAM:
            out.extend(["--retry_beam", _MFA_RETRY_BEAM])
            i += 2
            continue
        out.append(_ENGLISH_MODEL_MAP.get(tok, tok))
        i += 1
    return out


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

    logger.info(
        "Engine C: MFA fast-mode enabled (--clean kept; beam=%s, retry_beam=%s).",
        _MFA_BEAM or "upstream",
        _MFA_RETRY_BEAM or "upstream",
    )

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
    # M2: don't surface weights/token on an unauthenticated endpoint.  The
    # `languages` list is cheap metadata the worker uses to decide whether
    # to bother POSTing an en-US request at all — it can't route on its own
    # anyway, so no information leakage beyond what's advertised by the API.
    return {"ok": True, "languages": list(_SUPPORTED_LANGS)}


@app.post("/engine_c/analyze")
async def analyze(
    audio: UploadFile = File(...),
    transcript: str = Form(...),
    language: str = Form("zh-CN"),
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

    lang = _normalize_lang(language)
    if not lang:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported language: {language!r}",
        )
    if lang not in _SUPPORTED_LANGS:
        raise HTTPException(
            status_code=503,
            detail=f"language {lang!r} assets not installed in sidecar",
        )

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
        # Run silencedetect in parallel with the main MFA pipeline — they're
        # independent (silencedetect forks its own ffmpeg; preprocessing.process
        # chdir's into tmp_dir for MFA) and the silence path is typically
        # 100-300 ms while MFA is 5-30 s, so the ffmpeg cost hides entirely
        # behind MFA.  asyncio.to_thread bridges the blocking calls into the
        # event loop; asyncio.gather waits for both.
        #
        # Safety note: preprocessing.process() does its own `os.chdir(tmp_dir)`,
        # so running two `analyze()` requests truly in parallel within one
        # worker would collide on cwd.  That's already an existing constraint
        # (see engine-c-multithread.md) — concurrent requests still need to be
        # serialized at the worker or uvicorn --workers level.  This change is
        # purely *intra-request* parallelism, which is safe.
        silence_task = asyncio.to_thread(_detect_silence, audio_bytes)
        pipeline_task = asyncio.to_thread(
            preprocessing.process, audio_bytes, transcript, tmp_dir, lang
        )
        silence_ranges, praat_output = await asyncio.gather(silence_task, pipeline_task)

        data = phones.parse(praat_output, lang)
        if not data.get("phones"):
            raise RuntimeError("MFA produced no alignment output")
        resonance.compute_resonance(data, _WEIGHTS_BY_LANG[lang], lang)
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
