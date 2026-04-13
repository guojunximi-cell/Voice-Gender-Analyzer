FROM alpine:latest as base
WORKDIR /build

# ── Stage 1: Node runtime ─────────────────────────────────────
FROM node:alpine AS node-base
ENV PNPM_HOME="/pnpm"
ENV PATH="${PNPM_HOME}:$PATH"
RUN corepack enable

FROM node-base AS web-deps
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    --mount=type=bind,source=pnpm-lock.yaml,target=pnpm-lock.yaml \
    --mount=type=bind,source=pnpm-workspace.yaml,target=pnpm-workspace.yaml \
    --mount=type=bind,source=package.json,target=package.json \
    --mount=type=bind,source=web/package.json,target=web/package.json \
    pnpm install --prod --frozen-lockfile

# ── Stage 2: Python runtime ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:alpine AS py-base
ENV UV_VENV_RELOCATABLE=1
ENV UV_NO_DEV=1

FROM py-base as py-deps
RUN --mount=type=cache,id=uv,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# ── Stage 3: Build ────────────────────────────────────────────
FROM node-base AS web-build
COPY . /build
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --no-editable \
    && pnpm run build:web

FROM py-base AS py-build
COPY . /build
RUN --mount=type=cache,id=uv,target=/root/.cache/uv \
    uv sync --locked --no-editable

RUN uv run ./scripts/init_iss_model.py
RUN uv run ./scripts/optimize_venv.py


# ── Prepare Image ─────────────────────────────────────────────
FROM base

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# COPY --from=web-build /build/web/node_modules /web/node_modules
COPY --from=web-build /build/web/dist /web

ENV PY_HOME="/.venv/bin"
COPY --from=py-build /build/.venv ${PY_HOME}
COPY --from=py-build /build/*.hdf5 /


# ── Run Project ───────────────────────────────────────────────
WORKDIR /
ENV GUNICORN_BIND=0.0.0.0:8000

ENV PATH="${PY_HOME}:$PATH"
CMD gunicorn voiceya:app \
    --bind ${GUNICORN_BIND} \
    --keep-alive 5 \
    --access-logfile=None \
    --error-logfile - \
    --proxy_headers=True \
    --forwarded_allow_ips="*"
