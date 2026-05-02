# Engine C sidecar: wraps gender-voice-visualization (vendored at
# voiceya/sidecars/visualizer-backend/) with a FastAPI shell exposing
# /engine_c/analyze.  Build context = voiceya repo root so we can copy the
# wrapper and the vendored source in one shot.
#
# Build:
#   docker build -f voiceya/sidecars/visualizer-backend.Dockerfile -t voiceya-engine-c:dev .
#
# Adapted from the upstream Dockerfile in the vendored project.  Differences:
#   - downloads both mandarin_mfa and english_mfa so a single deployment can
#     service zh-CN and en-US (picked per request via the `language` form field)
#   - installs fastapi/uvicorn/python-multipart into the mfa conda env
#   - replaces CGIHTTPServer (serve.py) with uvicorn + wrapper.main:app
#   - sidecar-friendly: no /tmp/gender-voice-rec leak, settings.recordings
#     points at an ephemeral per-request path.

FROM mambaorg/micromamba:1.5.8

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg sox praat libmagic1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN micromamba create -y -n mfa -c conda-forge \
        python=3.11 montreal-forced-aligner \
    && micromamba clean -a -y

ENV MAMBA_ROOT_PREFIX=/opt/conda
ENV MFA_BIN=/opt/conda/envs/mfa/bin/mfa
ENV PATH=/opt/conda/envs/mfa/bin:$PATH
ENV MFA_ROOT_DIR=/opt/mfa_root
RUN mkdir -p /opt/mfa_root && chmod -R 777 /opt/mfa_root

# Pre-download Mandarin + English acoustic models + dictionaries.
#
# Mandarin: the published v3 ``mandarin_mfa`` acoustic model uses a
# simplified tone-mark phone set (e.g. ``i˥`` instead of the legacy
# ``i˥˥``).  The legacy ``mandarin_mfa`` dictionary still ships the old
# double-tone phones, so pairing the v3 acoustic with the legacy dict
# leaves ~80 k common entries with phones that aren't in the model and
# wrapper/preloaded_aligner.py's inventory filter discards them — common
# hanzi like 春/风/花/光/霜 then appear as ``<unk>`` in MFA output.
# ``mandarin_china_mfa`` is the v3-aligned dictionary (per the acoustic
# model's own meta.json: ``dictionaries.names = ["mandarin_china_mfa",
# "mandarin_taiwan_mfa"]``); we still keep the legacy ``mandarin_mfa``
# dict around because the vendored subprocess MFA fallback expects it.
# English uses `english_us_arpa` (ARPABET output) rather than `english_mfa`
# (IPA) because the vendored cmudict.txt and stats.json are ARPABET-keyed —
# the wrapper's subprocess shim rewrites the literal `english_mfa` emitted by
# preprocessing.py into `english_us_arpa` so the vendored source stays
# untouched (see wrapper/main.py _tune_mfa_args).
RUN micromamba run -n mfa mfa model download acoustic mandarin_mfa \
 && micromamba run -n mfa mfa model download dictionary mandarin_mfa \
 && micromamba run -n mfa mfa model download dictionary mandarin_china_mfa \
 && micromamba run -n mfa mfa model download acoustic english_us_arpa \
 && micromamba run -n mfa mfa model download dictionary english_us_arpa \
 && micromamba run -n mfa mfa model download acoustic french_mfa \
 && micromamba run -n mfa mfa model download dictionary french_mfa \
 && micromamba run -n mfa mfa model inspect acoustic mandarin_mfa \
 && micromamba run -n mfa mfa model inspect acoustic english_us_arpa \
 && micromamba run -n mfa mfa model inspect acoustic french_mfa

# mandarin_mfa G2P/alignment implicit deps.
# Versions pinned from the known-good build (2026-04-17).
RUN micromamba run -n mfa pip install --no-cache-dir \
        "python-magic==0.4.27" \
        "spacy-pkuseg==1.0.1" "dragonmapper==0.3.0" "hanziconv==0.3.2" \
        "fastapi==0.136.0" "uvicorn[standard]==0.44.0" "python-multipart==0.0.26"

WORKDIR /app

# Vendored gender-voice-visualization tree → /app (so that relative paths
# like `stats_zh.json` / `mandarin_dict.txt` / `stats.json` / `cmudict.txt`
# resolve at import time just like upstream backend.cgi expects).
COPY voiceya/sidecars/visualizer-backend/ /app/

# FastAPI wrapper (voiceya-owned, not vendored).
COPY voiceya/sidecars/wrapper/ /app/wrapper/

# French MFA dictionary: copy from MFA pretrained cache into /app so phones.py
# can find it under the bare relative name expected by the vendored library.
# mandarin_dict.txt + cmudict.txt are committed to the repo (vendored from
# upstream); french_mfa_dict.txt isn't, so we materialise it here from the
# build-time `mfa model download dictionary french_mfa` cache.  Without
# stats_fr.json (produced by scripts/train_stats_fr.py), fr won't appear in
# /healthz `languages` and worker requests gracefully fall back to engine_c=null.
# `find` is defensive against MFA storing the dict under a different
# extension (.dict / .yaml / .txt) across versions — we just take the first
# match keyed on the registry name.
RUN F=$(find /opt/mfa_root/pretrained_models/dictionary \
              -name 'french_mfa*' -type f 2>/dev/null | head -1) \
 && test -n "$F" \
 && cp "$F" /app/french_mfa_dict.txt \
 && head -1 /app/french_mfa_dict.txt

# Settings must match in-container binary locations; upstream ships settings
# for local dev where paths differ.
RUN printf '{\n\
\t"dev"        : false,\n\
\t"logs"       : "",\n\
\t"recordings" : "/tmp/voiceya-engine-c/",\n\
\t"ffmpeg"     : "/usr/bin/ffmpeg",\n\
\t"sox"        : "/usr/bin/sox",\n\
\t"mfa"        : "/opt/conda/envs/mfa/bin/mfa",\n\
\t"praat"      : "/usr/bin/praat"\n\
}\n' > /app/settings.json \
 && mkdir -p /tmp/voiceya-engine-c

ENV PYTHONUTF8=1
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8001/healthz || exit 1

CMD ["micromamba", "run", "-n", "mfa", "uvicorn", "wrapper.main:app", \
     "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
