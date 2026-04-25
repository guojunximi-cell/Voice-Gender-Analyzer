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
# torch / torchaudio 是 funasr AutoModel 的隐式必需项（funasr METADATA 没声明，
# 但 auto_model.py 顶层无条件 import）；pyproject.toml 里显式声明并 pin 到
# PyTorch 官方 CPU index，避免引入 CUDA 轮子。
RUN uv sync --locked --no-dev --no-editable

# 下载 inaSpeechSegmenter 模型到 /root/.keras/inaSpeechSegmenter/（remote_utils 运行时会优先查这里）
RUN /build/.venv/bin/python scripts/init_iss_model.py

# Engine C: 预下载 FunASR Paraformer-zh 模型到 $MODELSCOPE_CACHE，
# 避免首请求在线下载。Engine C 关闭时运行时也不会加载该模型。
#
# 走自家 GitHub Release(Apache 2.0 license, mirrored from ModelScope)
# 而非直连 ModelScope——后者在 Railway 境外 build 节点上 ~200 kB/s，944 MB
# 要 ~50 min 才能拉完，撞 daemon ~40 min timeout 一定 fail。GitHub
# Releases CDN 在大多数 build region 都 30-100 MB/s，秒级完成。
#
# fail-open: 网络/校验失败时清空残留缓存并继续构建；engine_c_asr._load_model
# 自带 lazy fallback，首次 Engine C 请求会在线下载（慢，但不阻塞部署）。
ARG PARAFORMER_ZH_URL=https://github.com/guojunximi-cell/Voice-Gender-Analyzer/releases/download/models-v1/paraformer-zh.tar.gz
# tarball top-level dir 是 ``modelscope/``，所以解到 /opt（不是 /opt/modelscope），
# 最终得到 /opt/modelscope/models/iic/... ——FunASR 的 MODELSCOPE_CACHE 期待的布局。
RUN curl -fsSL "$PARAFORMER_ZH_URL" | tar -xzf - -C /opt \
    || (echo "WARNING: FunASR Paraformer-zh preload skipped (download failed) — runtime will lazy-download on first Engine C request" \
        && rm -rf /opt/modelscope \
        && mkdir -p /opt/modelscope)


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
