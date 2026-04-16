# syntax=docker/dockerfile:1.7

# ── Stage 1: 前端构建 ────────────────────────────────────────────
FROM node:20-bookworm-slim AS web-build
ENV PNPM_HOME="/pnpm"
ENV PATH="${PNPM_HOME}:${PATH}"
RUN corepack enable
WORKDIR /build

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY web/package.json web/package.json

RUN pnpm install --frozen-lockfile

COPY web/ web/
RUN pnpm run build:web

# ── Stage 2: Python 依赖 + 模型下载 ──────────────────────────────
FROM python:3.13-slim-bookworm AS py-build

# uv: 官方镜像只发布 uv 二进制，这里拷过来用
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 构建时依赖：libsndfile1 / ffmpeg 给 init_iss_model.py 预热模型用
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libsndfile1 \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV UV_NO_DEV=1 \
    UV_LINK_MODE=copy

WORKDIR /build
COPY . .

# 安装依赖到 /build/.venv（--no-editable 让项目以 wheel 形式装进 site-packages）
RUN uv sync --locked --no-dev --no-editable

# TODO: 兜底补齐 voiceya 子模块树——实测 hatch wheel 确认带齐后可删
RUN cp -r /build/voiceya/inaSpeechSegmenter /build/.venv/lib/python3.13/site-packages/voiceya/

# 下载 inaSpeechSegmenter 模型到 /root/.keras/inaSpeechSegmenter/（remote_utils 运行时会优先查这里）
RUN /build/.venv/bin/python scripts/init_iss_model.py


# ── Stage 3: 运行时镜像 ─────────────────────────────────────────
FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        libgomp1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=py-build /build/.venv /opt/venv
COPY --from=py-build /root/.keras /root/.keras
COPY --from=web-build /build/web/dist /app/web
COPY docker/start.py /app/start.py

ENV PATH="/opt/venv/bin:${PATH}" \
    WEB_DIR=/app/web \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app
EXPOSE 8080

CMD ["python", "/app/start.py"]
