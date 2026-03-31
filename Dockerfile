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

# ── System deps ───────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install inaSpeechSegmenter from local source ──────────────
COPY inaSpeechSegmenter-interspeech23/ ./inaSpeechSegmenter-interspeech23/
RUN pip install --no-cache-dir ./inaSpeechSegmenter-interspeech23/

# ── Install remaining Python dependencies ─────────────────────
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# ── Pre-download AI models (baked into image, no cold-start delay) ──
RUN python -c "from inaSpeechSegmenter import Segmenter; Segmenter(detect_gender=True); print('Models ready')"

# ── Copy built frontend ───────────────────────────────────────
COPY --from=frontend-builder /app/dist ./frontend/dist

# ── Copy application code ─────────────────────────────────────
COPY main.py acoustic_analyzer.py ./

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
