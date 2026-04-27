[简体中文](./README.zh-CN.md) | **English**

# Voice Gender Analyzer

> Browser-based gender, acoustic, and phoneme-level analysis of short voice clips — powered by deep-learning VAD and forced alignment. Upload or record an audio clip and read its gender expression, pitch, formants, and per-phoneme acoustics on a single page. The maximum duration is operator-configurable (`MAX_AUDIO_DURATION_SEC`, default 180s).

[![license](https://img.shields.io/badge/license-MPL--2.0-green)](./LICENSE)
[![python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![node](https://img.shields.io/badge/node-%E2%89%A520-green)](https://nodejs.org/)

---

## Features

- **Multi-engine analysis pipeline**
  - **Engine A — K-3** (based on [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter), [k3-cat fork](https://github.com/k3-cat/inaSpeechSegmenter)): VAD + male / female / music / noise segmentation
  - **Engine C**: ASR → [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) → [Praat](https://www.fon.hum.uva.nl/praat/) formants → per-phoneme z-score
- **Bilingual ASR (Engine C)**
  - `zh-CN` — [FunASR](https://github.com/modelscope/FunASR) Paraformer-zh
  - `en-US` — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`base.en` by default; `tiny / small / medium` selectable)
- **Interactive visualization**
  - Waveform with male / female colored bands and clickable segment slices
  - Three-row "sandwich" timeline: pitch heatmap on top, karaoke-style transcript in the middle, resonance heatmap on the bottom — character-aligned
  - Pitch p5–p95 frosted capsule + gender bar in a unified visual language
  - File-level metrics panel: mean / median / std / gender ratio
- **Persistent history**
  - IndexedDB keeps 50 sessions and 500 MB of raw audio (LRU eviction); survives reload
  - Gender-ratio scatter plot toggles between three label sources: Engine A / pitch / resonance

## Tech Stack

| Layer | Components |
|---|---|
| Frontend | Vanilla JS · [Vite](https://vitejs.dev/) · [WaveSurfer.js](https://wavesurfer.xyz/) · [uPlot](https://github.com/leeoniya/uPlot) |
| Backend | Python 3.13 · [FastAPI](https://fastapi.tiangolo.com/) · [Uvicorn](https://www.uvicorn.org/) · [Taskiq](https://taskiq-python.github.io/) · [Redis](https://redis.io/) |
| Engine A | [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter) (K-3 / TensorFlow 2), [k3-cat fork](https://github.com/k3-cat/inaSpeechSegmenter) |
| Engine C | [FunASR](https://github.com/modelscope/FunASR) · [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) · [Praat](https://www.fon.hum.uva.nl/praat/) · [gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization) sidecar |
| Deployment | Docker Compose · [Railway](https://railway.app/) |

## Local Development

Requires **Python 3.13**, [Node.js ≥ 20](https://nodejs.org/) (with pnpm), [uv](https://docs.astral.sh/uv/), and a local Redis.

```bash
git clone --recurse-submodules https://github.com/guojunximi-cell/Voice-Gender-Analyzer.git
cd Voice-Gender-Analyzer
uv sync                 # install Python deps from uv.lock into .venv
pnpm install -C web     # frontend deps
python run_app.py       # one-shot: redis + uvicorn + taskiq worker + vite
```

`run_app.py` spawns four processes concurrently and opens <http://localhost:5173> in your browser (Vite proxies API requests to `:8080`).

### Common commands

```bash
# Backend only (no Vite)
python -m voiceya

# Worker only
python -m taskiq worker voiceya.taskiq:broker voiceya.tasks.analyser --workers 1 --log-level INFO

# Production frontend build
pnpm --filter ./web run build

# Lint & format
ruff check . && ruff format .
pnpm --filter ./web run lint
pnpm --filter ./web run fmt:fix

# Tests (no pytest dependency, plain Python)
python tests/test_chunker.py
python tests/test_multichunk_merge.py
```

## Engine C

Engine C runs in a separate sidecar container alongside the API and worker.

```bash
cp .env.example .env              # set ENGINE_C_ENABLED=true
docker compose --profile engine-c up -d --build
```

The first build downloads FunASR weights and the MFA `mandarin_mfa` model (~2.5 GB, ~10 minutes). Subsequent starts are seconds. If the sidecar is unreachable or fails, `summary.engine_c = null` and Engine A still returns normally.

The sidecar source is vendored from [guojunximi-cell/gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization) under `voiceya/sidecars/visualizer-backend/`. A thin FastAPI wrapper lives in `voiceya/sidecars/wrapper/main.py`. Upstream sync follows the rsync steps in [`voiceya/sidecars/README.md`](./voiceya/sidecars/README.md).

### Standalone sidecar image

```bash
docker build -f voiceya/sidecars/visualizer-backend.Dockerfile -t voiceya-engine-c:dev .
docker run --rm -p 8001:8001 voiceya-engine-c:dev
curl http://localhost:8001/healthz
```

## Self-Hosting via Docker

```bash
cp .env.example .env
docker compose --profile engine-c up -d --build    # full pipeline (A + C)
# without the Engine C sidecar (Engine A only):
docker compose up -d --build
```

The service listens on `http://localhost:8080`. First build takes 10–15 minutes (TensorFlow + inaSpeechSegmenter weights are large). Configurable fields are in `.env.example`.

## Railway Deployment

Two paths, see [`docs/RAILWAY_DEPLOY.md`](./docs/RAILWAY_DEPLOY.md) for details:

- **CLI bootstrap** — `bash scripts/railway-bootstrap.sh`. Idempotently provisions app + worker + Redis (optionally + Engine C sidecar) and wires variable references.
- **Manual UI** — Railway → New Project → Deploy from GitHub → add Redis → set `REDIS_URL = ${{Redis.REDIS_URL}}`.

> Recommend ≥ 1 GB RAM per service. The Engine C sidecar uses `railway.sidecar.toml` and needs ≥ 4 GB to run MFA reliably.

## API

```http
POST /analyze-voice
Content-Type: multipart/form-data

file:     <audio blob, ≤ MAX_FILE_SIZE_MB, ≤ MAX_AUDIO_DURATION_SEC seconds>
language: zh-CN | en-US           # optional, default zh-CN
script:   <optional reference text — bypasses ASR in Engine C>
```

```http
GET /status/{task_id}
Accept: text/event-stream
```

The `language` field routes Engine C: `zh-CN` selects FunASR Paraformer-zh + `mandarin_mfa` + `stats_zh.json`; `en-US` selects faster-whisper + `english_us_arpa` + `stats.json`. Script mode bypasses ASR for both languages and uses the supplied transcript directly.

The status endpoint streams progress via Redis Streams (not pub/sub), so late clients can replay events from the beginning.

## Configuration

Full list in [`.env.example`](./.env.example) and `voiceya/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | — | Taskiq queue + SSE event bus (required) |
| `MAX_FILE_SIZE_MB` | 10 | Per-upload size limit |
| `MAX_AUDIO_DURATION_SEC` | 180 | Audio longer than this is rejected with HTTP 400 |
| `MAX_CONCURRENT` | 2 | Taskiq worker concurrency |
| `MAX_QUEUE_DEPTH` | 30 | Queue back-pressure threshold |
| `RATE_LIMIT_CT` | 10 | Requests allowed per window |
| `RATE_LIMIT_DURATION_SEC` | 60 | Rate-limit window |
| `TASK_MAX_EXEC_SEC` | 900 | Per-task execution ceiling |
| `ENGINE_C_ENABLED` | `false` | Master switch; when `false`, FunASR is never imported |
| `ENGINE_C_SIDECAR_URL` | `http://visualizer-backend:8001` | Worker → sidecar address |
| `ENGINE_C_SIDECAR_TOKEN` | empty | Shared bearer between worker and sidecar; set this in production |
| `ENGINE_C_SIDECAR_TIMEOUT_SEC` | 60 | Per-request HTTP timeout |
| `ENGINE_C_MIN_DURATION_SEC` | 3 | Audio shorter than this skips Engine C |
| `ENGINE_C_MAX_AUDIO_MB` | 50 | Sidecar per-request audio cap (defense-in-depth) |
| `ENGINE_C_WHISPER_MODEL` | `base.en` | faster-whisper model id (`tiny.en` / `small.en` / `medium.en`) |
| `ENGINE_C_WHISPER_DEVICE` | `auto` | `auto` picks CUDA if available, else CPU |
| `ENGINE_C_WHISPER_COMPUTE_TYPE` | `int8` | CT2 compute type; `int8` balances speed and size on CPU |

## Architecture

```
Browser POST /analyze-voice
  └─ routers/api.py           → file/duration validation, analyse_voice.kiq()
       └─ Redis Stream         → taskiq broker (RedisStreamBroker)
            └─ worker process  → voiceya/tasks/analyser.py::analyse_voice
                 └─ services/audio_analyser/__init__.py::do_analyse
                      ├─ Engine A: do_segmentation()
                      └─ Engine C: run_engine_c()

Browser GET /status/{task_id}  (Accept: text/event-stream)
  └─ subscribe_to_events_and_generate_sse()
       └─ Redis XREAD (streamed replay; late clients see every event)
```

The API process and the worker process are separated: **the API never loads TensorFlow models** (saves ~500 MB). It only dispatches tasks and forwards SSE events. `load_seg()` only fires when `broker.is_worker_process` is true.

## Code Structure

```
voiceya/                           backend package
├── routers/api.py                 FastAPI routes (SSE in services/sse.py)
├── services/
│   ├── audio_analyser/
│   │   ├── engine_a.py            VAD + gender segmentation (K-3)
│   │   ├── engine_c.py            Engine C orchestrator (ASR → sidecar)
│   │   ├── engine_c_asr.py        FunASR Paraformer-zh (SHA-256 LRU cache)
│   │   ├── engine_c_asr_en.py     faster-whisper, returns word_timestamps
│   │   └── acoustic_analyzer.py   Engine B (deprecated, see below)
│   ├── sse.py / events_stream.py  SSE event bus
│   └── ...
├── sidecars/
│   ├── visualizer-backend/        vendored from gender-voice-visualization
│   ├── wrapper/main.py            FastAPI wrapper + MFA parameter shim
│   └── visualizer-backend.Dockerfile
├── inaSpeechSegmenter/            git submodule → k3-cat/inaSpeechSegmenter
├── taskiq.py                      worker broker
└── config.py                      Pydantic Settings
web/
├── src/
│   ├── main.js                    entry: IndexedDB + SSE + orchestration
│   └── modules/                   UI components (heatmap-band, metrics-panel, waveform, ...)
└── ...
docker-compose.yml                 app + worker + redis (+ engine-c profile)
railway.toml / railway.sidecar.toml
```

## Deprecated

**Engine B** — LPC-formant + composite gender score (`voiceya/services/audio_analyser/acoustic_analyzer.py`). Outputs are no longer surfaced to the client as of **2026-04-07**, but the code remains in the repository for reference and to keep the multi-engine option open.

## Conventions

- **Python** — Ruff (`.ruff.toml`: py313, double quotes, snake_case, LF)
- **Frontend** — oxlint + Prettier (tabs, 120-column, camelCase, sorted imports)
- **EditorConfig** — covers indent / line-ending across all languages
- **Vendor directories** (`voiceya/inaSpeechSegmenter/`, `voiceya/sidecars/visualizer-backend/`) are not to be replaced or reset; upstream sync follows the rsync steps in [`voiceya/sidecars/README.md`](./voiceya/sidecars/README.md)
- **Branches** — `dev-en` for English-language work; merging to `main` only on explicit authorization, no cross-branch cherry-picks

## Acknowledgements

- [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter) — Doukhan et al., ICASSP 2018 (MIT)
- [k3-cat/inaSpeechSegmenter](https://github.com/k3-cat/inaSpeechSegmenter) — K-3 compatibility fork
- [FunASR](https://github.com/modelscope/FunASR) — Paraformer-zh ASR (Apache-2.0)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 Whisper inference (MIT)
- [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) — forced alignment (MIT)
- [gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization) — Engine C sidecar source
- [WaveSurfer.js](https://wavesurfer.xyz/) · [uPlot](https://github.com/leeoniya/uPlot)

Source code is released under **MPL-2.0**. See [`LICENSE`](./LICENSE).

This tool is intended for academic research and voice-technology learning. Gender analysis results are derived from statistical acoustic models and **do not constitute a judgment about an individual's gender identity**.
