WORKDIR /build

# ── Stage 1: Node runtime ─────────────────────────────────────
FROM node:24-alpine AS node-base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable && corepack prepare pnpm@latest --activate

FROM node-base AS web-deps
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    --mount=type=bind,source=pnpm-lock.yaml,target=pnpm-lock.yaml \
    --mount=type=bind,source=pnpm-workspace.yaml,target=pnpm-workspace.yaml \
    --mount=type=bind,source=package.json,target=package.json \
    --mount=type=bind,source=web/package.json,target=web/package.json \
    pnpm install --prod --frozen-lockfile

# ── Stage 2: Python runtime ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:alpine AS py-base
ENV UV_NO_DEV=1

FROM py-base as backend-deps
RUN --mount=type=cache,id=uv,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# ── Stage 3: Build ────────────────────────────────────────────
COPY . /build

FROM node-base AS web-build
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile \
    && pnpm run build:web

FROM py-base AS backend-build
RUN --mount=type=cache,id=uv,target=/root/.cache/uv \
    uv sync --locked

RUN python ./scripts/init_iss_model.py


# ── Prepare Image ─────────────────────────────────────────────
From alpine:latest
WORKDIR /

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# COPY --from=web-build /build/web/node_modules /web/node_modules
COPY --from=web-build /build/web/dist /web

COPY --from=backend-build /build/.venv /.venv
COPY --from=backend-build /build/backend /backend
COPY --from=backend-build /build/*.hdf5 /


# ── Run Project ───────────────────────────────────────────────
ENV GUNICORN_BIND=0.0.0.0:8000

CMD gunicorn backend:app \
        --bind $GUNICORN_BIND \
        --keep-alive 5 \
        --access-logfile=None \
        --error-logfile - \
        --proxy_headers=True \
        --forwarded_allow_ips="*"
