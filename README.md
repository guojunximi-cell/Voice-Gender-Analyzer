[简体中文](./README.zh-CN.md) | **English**

# Voiceduck

> View phoneme-aligned F0 and resonance on a single page, backed by a neural-network classifier as a reference. The author hopes it can help with voice training.

[![license](https://img.shields.io/badge/license-MPL--2.0-green)](./LICENSE)
[![python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![node](https://img.shields.io/badge/node-%E2%89%A520-green)](https://nodejs.org/)

---

# Architecture

```
Browser POST /analyze-voice
  └─ routers/api.py           → file / duration validation, analyse_voice.kiq()
       └─ Redis Stream         → taskiq broker (RedisStreamBroker)
            └─ worker process  → voiceya/tasks/analyser.py::analyse_voice
                 └─ services/audio_analyser/__init__.py::do_analyse
                      ├─ Engine A: do_segmentation()
                      └─ Engine C: run_engine_c()

Browser GET /status/{task_id}  (Accept: text/event-stream)
  └─ subscribe_to_events_and_generate_sse()
       └─ Redis XREAD (streamed replay)
```

## Local Development

Requires **Python 3.13** · [Node.js ≥ 20](https://nodejs.org/) (with pnpm) · [uv](https://docs.astral.sh/uv/) · a local Redis.

```bash
git clone --recurse-submodules https://github.com/guojunximi-cell/Voice-Gender-Analyzer.git
cd Voice-Gender-Analyzer
uv sync                 # install Python deps from uv.lock into .venv
pnpm install -C web     # frontend deps
python run_app.py       # one-shot: redis + uvicorn + taskiq worker + vite
```

`run_app.py` spawns four processes concurrently and opens <http://localhost:5173>.

## Engine C

Engine C runs in a separate sidecar container alongside the API and worker.

```bash
cp .env.example .env              # set ENGINE_C_ENABLED=true
docker compose --profile engine-c up -d --build
```

## Docker

```bash
cp .env.example .env
docker compose --profile engine-c up -d --build    # full pipeline (A + C)
# without the Engine C sidecar (Engine A only):
docker compose up -d --build
```

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

## Configuration

See [`.env.example`](./.env.example) and `voiceya/config.py`.

## Railway Deployment

See [`docs/RAILWAY_DEPLOY.md`](./docs/RAILWAY_DEPLOY.md).


## Deprecated

**Engine B** (`voiceya/services/audio_analyser/acoustic_analyzer.py`)

## Citations

### Models / aligners / toolkits

- **inaSpeechSegmenter**
  Doukhan, D., Carrive, J., Vallet, F., Larcher, A., & Meignier, S. (2018). *An open-source speaker gender detection framework for monitoring gender equality.* ICASSP 2018.
- **FunASR / Paraformer-zh**
  Gao, Z., Zhang, S., McLoughlin, I., & Yan, Z. (2022). *Paraformer: Fast and Accurate Parallel Transformer for Non-autoregressive End-to-End Speech Recognition.* Interspeech 2022.
  Gao, Z. et al. (2023). *FunASR: A Fundamental End-to-End Speech Recognition Toolkit.* Interspeech 2023.
- **Whisper / faster-whisper**
  Radford, A., Kim, J. W., Xu, T., Brockman, G., McLeavey, C., & Sutskever, I. (2022). *Robust Speech Recognition via Large-Scale Weak Supervision.* OpenAI.
- **Montreal Forced Aligner (MFA)**
  McAuliffe, M., Socolof, M., Mihuc, S., Wagner, M., & Sonderegger, M. (2017). *Montreal Forced Aligner: Trainable text-speech alignment using Kaldi.* Interspeech 2017.
- **Praat**
  Boersma, P., & Weenink, D. (2024). *Praat: doing phonetics by computer*

### Pretrained MFA acoustic models & dictionaries

- `mandarin_mfa` v2.0.0 — `zh-CN`
- `english_us_arpa` — `en-US`
- `french_mfa` — `fr-FR`

### Corpora used to build `stats_*.json`

- **AISHELL-1** ([OpenSLR-33](https://www.openslr.org/33/)) — 400 speakers → contributes to `stats_zh.json` v0.2.0.
  Bu, H., Du, J., Na, X., Wu, B., & Zheng, H. (2017). *AISHELL-1: An Open-Source Mandarin Speech Corpus and a Speech Recognition Baseline.* O-COCOSDA 2017.
- **AISHELL-3** ([OpenSLR-93](https://www.openslr.org/93/)) — 218 speakers → contributes to `stats_zh.json` v0.2.0.
  Shi, Y., Bu, H., Xu, X., Zhang, S., & Li, M. (2021). *AISHELL-3: A Multi-Speaker Mandarin TTS Corpus and the Baselines.* Interspeech 2021.
- **Common Voice — Mozilla Data Collective, Scripted Speech 25.0 (fr)** — 2026-03-09 dump, 984F + 3793M speakers → `stats_fr.json` v0.1.0.
  Ardila, R., Branson, M., Davis, K., Henretty, M., Kohler, M., Meyer, J., Morais, R., Saunders, L., Tyers, F. M., & Weber, G. (2020). *Common Voice: A Massively-Multilingual Speech Corpus.* LREC 2020. — [dataset](https://mozilladatacollective.com/) (CC0-1.0)

For the full training protocol see [`voiceya/sidecars/visualizer-backend/CHANGELOG_ZH.md`](./voiceya/sidecars/visualizer-backend/CHANGELOG_ZH.md) and [`CHANGELOG_FR.md`](./voiceya/sidecars/visualizer-backend/CHANGELOG_FR.md).

### Vendored components

- [**gender-voice-visualization**](https://github.com/guojunximi-cell/gender-voice-visualization) — Engine C sidecar source (`working-chinese-version` branch); see [`voiceya/sidecars/README.md`](./voiceya/sidecars/README.md) for the rsync sync protocol.
- [**k3-cat/inaSpeechSegmenter**](https://github.com/k3-cat/inaSpeechSegmenter) — K-3 / TensorFlow 2 compatibility fork of inaSpeechSegmenter, included as a git submodule.

### Frontend libraries

[Vite](https://vitejs.dev/) · [WaveSurfer.js](https://wavesurfer.xyz/) · [uPlot](https://github.com/leeoniya/uPlot)

## License & Disclaimer

See [`LICENSE`](./LICENSE).
