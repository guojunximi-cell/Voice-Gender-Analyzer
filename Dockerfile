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
# build-essential (g++ 等) 是 editdistance 0.8.1 (funasr 间接依赖) 编译 Cython 扩展所必需的。
# git 给下方 submodule 兜底用：Railway 的 build context 不 recurse submodule，
# 需要检测空目录再手动 clone。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libsndfile1 \
        ffmpeg \
        ca-certificates \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

ENV UV_NO_DEV=1 \
    UV_LINK_MODE=copy \
    MODELSCOPE_CACHE=/opt/modelscope

WORKDIR /build
COPY . .

# Railway 兜底：build context 不 recurse submodule 时，gitlink 目录为空。
# 检测不到 submodule 的 setup.py 就手动 clone 到对应 commit。
# 本地 submodule 已填充时 test -f 直接跳过，不影响本地构建。
ARG INA_SS_COMMIT=7568394
RUN test -f voiceya/inaSpeechSegmenter/setup.py \
    || (rm -rf voiceya/inaSpeechSegmenter \
        && git clone https://github.com/k3-cat/inaSpeechSegmenter.git voiceya/inaSpeechSegmenter \
        && git -C voiceya/inaSpeechSegmenter checkout ${INA_SS_COMMIT})

# 安装依赖到 /build/.venv（--no-editable 让项目以 wheel 形式装进 site-packages）
RUN uv sync --locked --no-dev --no-editable

# torch (CPU-only) 是 funasr AutoModel 的隐式必需项——funasr 不在 PyPI 元数据里声明它，
# 但 auto_model.py 在顶层无条件 import torch。
# 用 PyTorch CPU 专用 index 而非 uv.lock，避免引入 CUDA 轮子并保持 lockfile 跨平台。
RUN uv pip install --no-cache-dir \
        --python /build/.venv/bin/python \
        "torch==2.11.0+cpu" "torchaudio==2.11.0+cpu" \
        --index-url https://download.pytorch.org/whl/cpu

# 下载 inaSpeechSegmenter 模型到 /root/.keras/inaSpeechSegmenter/（remote_utils 运行时会优先查这里）
RUN /build/.venv/bin/python scripts/init_iss_model.py

# Engine C: 预下载 FunASR Paraformer-zh ONNX 模型到 $MODELSCOPE_CACHE，
# 避免首请求在线下载。Engine C 关闭时运行时也不会加载该模型。
RUN /build/.venv/bin/python -c "from funasr import AutoModel; AutoModel(model='paraformer-zh', disable_update=True, disable_log=True)"


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
COPY --from=py-build /opt/modelscope /opt/modelscope
COPY --from=web-build /build/web/dist /app/web
COPY docker/start.py /app/start.py

ENV PATH="/opt/venv/bin:${PATH}" \
    WEB_DIR=/app/web \
    MODELSCOPE_CACHE=/opt/modelscope \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app
EXPOSE 8080

CMD ["python", "/app/start.py"]
