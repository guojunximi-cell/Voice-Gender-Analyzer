# ── Stage 1: Build frontend ───────────────────────────────────
FROM node:20-slim AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# Output: /app/dist/

# ── Stage 2: Python runtime ───────────────────────────────────
FROM python:3.11-slim

# ── uv (fast Python package manager) ─────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ── System deps ───────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install Python dependencies (PyPI) ────────────────────────
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# ── Install inaSpeechSegmenter from local source (AFTER PyPI) ─
# Must come after requirements.txt so our patched version
# (with per-frame confidence data) overwrites the stock PyPI build.
COPY inaSpeechSegmenter-interspeech23/ ./inaSpeechSegmenter-interspeech23/
RUN uv pip install --system --no-cache --force-reinstall --no-deps ./inaSpeechSegmenter-interspeech23/

# ── Pre-download AI models (baked into image, no cold-start delay) ──
RUN python -c "from inaSpeechSegmenter import Segmenter; Segmenter(detect_gender=True); print('Models ready')"

# ── Copy built frontend ───────────────────────────────────────
COPY --from=frontend-builder /app/dist ./frontend/dist

# ── Copy application code ─────────────────────────────────────
COPY main.py ./

# ── Railway injects $PORT at runtime ──────────────────────────
ENV PORT=8000

# gunicorn + uvicorn workers: 1 worker keeps a single model in memory
# Increase --workers if Railway plan has enough RAM (each worker ~1–2 GB)
CMD gunicorn main:app \
        --worker-class uvicorn.workers.UvicornWorker \
        --workers 1 \
        --bind 0.0.0.0:$PORT \
        --timeout 300 \
        --graceful-timeout 30 \
        --keep-alive 5 \
        --access-logfile - \
        --error-logfile -
