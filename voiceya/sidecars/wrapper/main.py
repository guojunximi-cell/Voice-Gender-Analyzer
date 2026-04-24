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

# Wrapper-local helpers (siblings of main.py).  Relative imports because
# uvicorn loads this module as ``wrapper.main`` so ``wrapper.chunker`` /
# ``wrapper.multichunk`` are the right absolute names, but ``from .`` is
# shorter and refactor-safe.
from . import chunker, multichunk
from .preloaded_aligner import PreloadedAligner

logger = logging.getLogger("engine_c.sidecar")

# Uvicorn installs handlers for its own loggers but leaves root unconfigured.
# Our engine_c.* loggers need an explicit StreamHandler or they fall through
# to root's "last resort" handler (WARNING+ only, hiding INFO traces).
# Attach once at module load.  Idempotent — guard against reload doubling.
_engine_c_handler = logging.StreamHandler()
_engine_c_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
for _name in (
    "engine_c.sidecar",
    "engine_c.chunker",
    "engine_c.multichunk",
    "engine_c.preloaded_aligner",
):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.INFO)
    # Replace any prior handler from a module reload so logs don't double.
    _lg.handlers = [_engine_c_handler]
    _lg.propagate = False

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


# ── Preloaded kalpy aligners (one per supported lang) ───────────────
# Built at module load so the expensive setup (acoustic model zip +
# lexicon FST compilation) is amortised across the container's lifetime
# instead of paid 27 s per request via the `mfa align` CLI subprocess.
#
# Scoped to English at first integration — the vendored single-block path
# still handles zh requests, and we'll extend once zh is validated.
# Set ENGINE_C_PRELOAD_ALIGNER=0 to force the old subprocess path
# everywhere (safety knob for regressions).
_PRELOAD_ENABLED = os.environ.get(
    "ENGINE_C_PRELOAD_ALIGNER", "1",
).lower() in ("1", "true", "yes", "on")

# Acoustic and dictionary names diverge for zh: the v3 mandarin_mfa
# acoustic model was published with simplified tone marks (e.g. ``i˥``
# instead of ``i˥˥``), but the legacy ``mandarin_mfa`` dictionary still
# uses the old double-tone phones — pairing them strips ~80 k entries
# in the phone-inventory filter and leaves common hanzi (春/风/花/光/霜)
# with no valid pronunciation, surfacing as ``<unk>`` in MFA's output.
# ``mandarin_china_mfa`` is the v3-aligned dictionary (per the model's
# own meta.json: ``dictionaries.names = ["mandarin_china_mfa", ...]``).
_ACOUSTIC_NAME_BY_LANG: dict[str, str] = {
    "en": "english_us_arpa",
    "zh": "mandarin_mfa",
}
_DICT_NAME_BY_LANG: dict[str, str] = {
    "en": "english_us_arpa",
    "zh": "mandarin_china_mfa",
}

_PRELOADED_ALIGNERS: dict[str, PreloadedAligner] = {}
if _PRELOAD_ENABLED:
    try:
        from montreal_forced_aligner.models import (  # noqa: PLC0415
            MODEL_TYPES as _MFA_MODEL_TYPES,
        )
        for _lang in _SUPPORTED_LANGS:
            _acoustic_name = _ACOUSTIC_NAME_BY_LANG.get(_lang)
            _dict_name = _DICT_NAME_BY_LANG.get(_lang)
            if not (_acoustic_name and _dict_name):
                continue
            try:
                _acoustic_path = _MFA_MODEL_TYPES["acoustic"].get_pretrained_path(_acoustic_name)
                _dict_path = _MFA_MODEL_TYPES["dictionary"].get_pretrained_path(_dict_name)
            except Exception as _exc:
                logger.warning(
                    "preload skipped for %s: can't resolve model path (%s)",
                    _lang, _exc,
                )
                continue
            _aligner = PreloadedAligner.load(_lang, _acoustic_path, _dict_path)
            if _aligner is None:
                continue
            # Warmup both pays the kalpy first-call JIT tax AND probes for
            # language-specific kalpy incompatibilities (notably
            # mandarin_mfa hits a phone-ID collision in CompileGraphFromText
            # on non-trivial transcripts — MFA's own align_one CLI has the
            # same bug).  Don't register aligners that fail warmup; they'll
            # only cost a per-request round-trip to the fallback path.
            if _aligner.warmup():
                _PRELOADED_ALIGNERS[_lang] = _aligner
    except ImportError as _exc:
        logger.warning(
            "preload disabled — MFA/kalpy imports failed: %s", _exc,
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

# ── Multi-chunk path (Engine-C en free mode) ────────────────────────
# When the worker ships ASR word timestamps, the sidecar can decode+slice
# the audio at silence boundaries and feed an N-file corpus to MFA with
# ``--num_jobs N`` for parallel alignment.  Falls back to the single-block
# path on any failure (no word timestamps, chunker declines, MFA errors,
# merge detects a zero-phone chunk).
#
# Scoped to English because zh needs FunASR word timestamps which aren't
# plumbed yet — ``lang == "en"`` guard in the endpoint keeps the zh path
# on its current single-block code route.
_CHUNK_ENABLED = os.environ.get("ENGINE_C_CHUNK_ENABLED", "1").lower() in ("1", "true", "yes", "on")


def _run_chunked_path(
    audio_bytes: bytes,
    transcript: str,
    word_timestamps: list[dict] | None,
    silence_ranges: list[dict],
    tmp_dir: str,
    lang: str,
    saved_cwd: str,
) -> dict | None:
    """Align via preloaded kalpy (multi-chunk when we have word timestamps,
    single-chunk otherwise); return merged data or None on decline/failure.

    Returning None is the documented fallback signal — the caller will run
    the vendored single-block pipeline (preprocessing.process) on the same
    request.  Exceptions are caught here (not re-raised) so a half-
    initialised kalpy path never kills a request.
    """
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        full_wav = os.path.join(tmp_dir, "full.wav")
        duration = multichunk.decode_to_wav(audio_bytes, full_wav, settings["ffmpeg"])

        # Chunker only pays off when alignment startup cost dominates
        # per-chunk wall time — i.e. with the subprocess MFA fallback.  When
        # a preloaded kalpy aligner is available, each align_utterance call
        # is sub-second already, so chunking just adds Praat + ffmpeg-slice
        # overhead for no gain (measured: 33 s audio single-chunk 0.90 s
        # vs. 3-chunk 1.31 s).  Only consult the chunker when we're on the
        # subprocess path.
        preloaded = _PRELOADED_ALIGNERS.get(lang)
        chunks: list[dict] | None = None
        if word_timestamps and preloaded is None:
            chunks = chunker.plan_chunks(duration, word_timestamps, silence_ranges)

        if not chunks:
            chunks = [{
                "index": 0,
                "start_sec": 0.0,
                "end_sec": duration,
                "transcript": transcript,
                "word_count": len(transcript.split()),
            }]
            logger.info(
                "kalpy: single-chunk path (%s)  duration=%.1fs",
                "preloaded aligner prefers it"
                if preloaded is not None
                else "no word_ts or chunker declined",
                duration,
            )
        else:
            logger.info(
                "subprocess MFA: %d chunks over %.1fs  durs=%s",
                len(chunks), duration,
                [round(c["end_sec"] - c["start_sec"], 2) for c in chunks],
            )

        # textgrid-formants.praat lives in the sidecar's startup cwd
        # (WORKDIR=/app).  Resolve absolutely because run_mfa (subprocess
        # fallback) chdirs into tmp_dir.
        praat_script = os.path.join(saved_cwd, "textgrid-formants.praat")
        merged = multichunk.process_from_wav(
            full_wav, chunks, tmp_dir, lang, settings, praat_script,
            mfa_beam=_MFA_BEAM if _FAST_MFA else "",
            mfa_retry_beam=_MFA_RETRY_BEAM if _FAST_MFA else "",
            preloaded_aligner=preloaded,
        )
        if merged is None:
            logger.info("kalpy: merge returned None — vendored fallback")
        return merged
    except Exception as exc:
        logger.warning("kalpy path: unexpected failure, falling back: %s", exc)
        logger.warning("kalpy trace:\n%s", traceback.format_exc())
        return None


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
    """Rewrite vendored preprocessing.py's mfa-align argv before launch.

    Three rewrites: (a) en model name → ``english_us_arpa`` so phones
    output match the ARPABET cmudict.txt/stats.json this sidecar ships;
    (b) beam / retry_beam to tighter values for fast-mode (speed); and
    (c) zh **dict** positional → ``mandarin_china_mfa`` so it matches
    the v3 acoustic model's phone set (the legacy ``mandarin_mfa`` dict
    pairs with the v3 acoustic model only after our inventory filter
    drops ~80 k common entries — leaving common hanzi as ``<unk>``).
    The acoustic model name stays ``mandarin_mfa`` because that's what
    upstream MFA's pretrained registry exposes for v3 zh.
    """
    out: list = []
    i = 0
    # ``mfa align CORPUS DICT ACOUSTIC OUTPUT [opts...]`` — track the
    # positional slot relative to ``align`` so we can target the DICT
    # arg (slot 2) without disturbing ACOUSTIC (slot 3).
    align_seen = False
    positional_after_align = 0
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
        # Positional tracking: anything starting with ``-`` is an option
        # (consume it without bumping the positional counter).
        if align_seen and not str(tok).startswith("-"):
            positional_after_align += 1
            # slot 2 is DICT — rewrite legacy mandarin_mfa to china variant.
            if positional_after_align == 2 and tok == "mandarin_mfa":
                out.append("mandarin_china_mfa")
                i += 1
                continue
        if tok == "align":
            align_seen = True
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
    word_timestamps_json: str | None = Form(default=None),
    x_engine_c_token: str | None = Header(default=None, alias="X-Engine-C-Token"),
) -> dict:
    """Run the upstream pipeline on a single audio clip + transcript.

    Returns the `data` dict from resonance.compute_resonance, which includes:
      - words:   [{time, word, expected: [phone, ...]}]
      - phones:  [{time, phoneme, word_index, expected, F, F_stdevs, resonance?}]
      - meanPitch / medianPitch / stdevPitch
      - meanResonance / medianResonance / stdevResonance
      - mean / stdev (F-vectors)

    ``word_timestamps_json``: optional JSON-encoded list of
    ``{word, start, end}`` from the worker's ASR.  When present and the chunk
    path is enabled, the sidecar splits audio + transcript at silence
    boundaries and runs MFA alignment in parallel across chunks.  Absent or
    malformed → fall back to the single-block pipeline (current behaviour).
    """
    _check_auth(x_engine_c_token)

    word_timestamps: list[dict] | None = None
    if word_timestamps_json:
        try:
            parsed = json.loads(word_timestamps_json)
            if isinstance(parsed, list) and all(isinstance(w, dict) for w in parsed):
                word_timestamps = parsed
        except json.JSONDecodeError as exc:
            logger.warning("word_timestamps_json ignored (parse error: %s)", exc)
    if word_timestamps is not None:
        logger.info("Engine C: received %d word timestamps", len(word_timestamps))

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

    # Chunked path needs its own tmp subtree because preprocessing.process
    # (single-block fallback) expects to own ``tmp_dir`` entirely (it calls
    # os.mkdir on it and rmtree at the end).  Keeping them separate also
    # keeps the finally-block cleanup simple — both get rmtree'd
    # unconditionally regardless of which path ran.
    chunk_tmp = tmp_dir + ".chunk"

    try:
        # Always compute silence ranges — needed by the chunker for cut-point
        # selection and surfaced to the frontend as authoritative sentence
        # boundaries.  Cost is ~100-300 ms (one ffmpeg silencedetect pass).
        silence_ranges = await asyncio.to_thread(_detect_silence, audio_bytes)

        # Try the kalpy path first when a preloaded aligner is available for
        # this language.  Covers both:
        #   - word_timestamps + chunker → balanced multichunk kalpy path
        #   - no word_timestamps (script mode, short audio) → single-chunk
        #     kalpy path on the full clip
        # Returns None on decline (aligner init failed, kalpy error, merge
        # detected a broken chunk); None triggers the vendored single-block
        # subprocess MFA fallback below.
        data: dict | None = None
        use_kalpy = (
            _CHUNK_ENABLED
            and lang in _PRELOADED_ALIGNERS
        )
        if use_kalpy:
            data = await asyncio.to_thread(
                _run_chunked_path,
                audio_bytes, transcript, word_timestamps, silence_ranges,
                chunk_tmp, lang, saved_cwd,
            )

        if data is None:
            # Single-block path — vendored preprocessing.process owns
            # ``tmp_dir`` (mkdir on entry, rmtree on success), and chdir's
            # into it for MFA.  That chdir is why concurrent requests still
            # need serialization at the worker / uvicorn-workers level.
            praat_output = await asyncio.to_thread(
                preprocessing.process, audio_bytes, transcript, tmp_dir, lang
            )
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
        # ignore_errors=True handles the case where process() already ran
        # its own rmtree on the happy path, and the common case where the
        # chunked path was never taken (chunk_tmp never created).
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(chunk_tmp, ignore_errors=True)
        # Restore cwd in case the vendored preprocessing.process or our
        # multichunk.run_mfa chdir'd into a tmp dir and raised before
        # restoring.  Both now call os.chdir back themselves, but this
        # belt-and-braces guard remains cheap and has caught real bugs.
        try:
            if os.getcwd() != saved_cwd:
                os.chdir(saved_cwd)
        except OSError:
            os.chdir(saved_cwd)
