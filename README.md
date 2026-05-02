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

Voiceduck builds on the following published tools, pretrained models, and datasets. References below have been verified against arXiv / ISCA Archive / ACL Anthology / OpenSLR; if you publish results derived from this project, please cite the upstream sources directly.

### Models, aligners & toolkits

- **inaSpeechSegmenter** — Engine A (VAD + gender segmentation).
  Doukhan, D., Carrive, J., Vallet, F., Larcher, A., & Meignier, S. (2018). *An Open-Source Speaker Gender Detection Framework for Monitoring Gender Equality.* ICASSP 2018. — [code](https://github.com/ina-foss/inaSpeechSegmenter) · [k3-cat fork](https://github.com/k3-cat/inaSpeechSegmenter) (MIT)
- **FunASR / Paraformer-zh** — Engine C ASR for `zh-CN`.
  Gao, Z., Zhang, S., McLoughlin, I., & Yan, Z. (2022). *Paraformer: Fast and Accurate Parallel Transformer for Non-autoregressive End-to-End Speech Recognition.* Interspeech 2022. ([ISCA archive](https://www.isca-archive.org/interspeech_2022/gao22b_interspeech.html))
  Gao, Z. et al. (2023). *FunASR: A Fundamental End-to-End Speech Recognition Toolkit.* Interspeech 2023. ([ISCA archive](https://www.isca-archive.org/interspeech_2023/gao23g_interspeech.html)) — [code](https://github.com/modelscope/FunASR) (Apache-2.0)
- **Whisper / faster-whisper** — Engine C ASR for `en-US` and `fr-FR`.
  Radford, A., Kim, J. W., Xu, T., Brockman, G., McLeavey, C., & Sutskever, I. (2022). *Robust Speech Recognition via Large-Scale Weak Supervision.* [arXiv:2212.04356](https://arxiv.org/abs/2212.04356); also ICML 2023. — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2 inference, MIT)
- **Montreal Forced Aligner (MFA)** — phone-level alignment.
  McAuliffe, M., Socolof, M., Mihuc, S., Wagner, M., & Sonderegger, M. (2017). *Montreal Forced Aligner: Trainable Text-Speech Alignment Using Kaldi.* Interspeech 2017, 498–502. ([ISCA archive](https://www.isca-archive.org/interspeech_2017/mcauliffe17_interspeech.html), [DOI](https://doi.org/10.21437/Interspeech.2017-1386)) — [docs](https://montreal-forced-aligner.readthedocs.io/) (MIT)
- **Praat** — formant tracking inside the Engine C sidecar.
  Boersma, P., & Weenink, D. (2026). *Praat: doing phonetics by computer* [Computer program]. Version 6.4.65. — [praat.org](https://www.fon.hum.uva.nl/praat/) ([How to cite](https://www.fon.hum.uva.nl/praat/manual/FAQ__How_to_cite_Praat.html))

### Pretrained MFA acoustic models & dictionaries

Sourced from the [MFA Models registry](https://mfa-models.readthedocs.io/), downloaded at sidecar build time:

- `mandarin_mfa` v2.0.0 — `zh-CN`
- `english_us_arpa` — `en-US`
- `french_mfa` — `fr-FR`

### Reference statistics — corpora used to build `stats_*.json`

- **AISHELL-1** ([OpenSLR-33](https://www.openslr.org/33/)) — 400 spk → contributes to `stats_zh.json` v0.2.0.
  Bu, H., Du, J., Na, X., Wu, B., & Zheng, H. (2017). *AISHELL-1: An Open-Source Mandarin Speech Corpus and a Speech Recognition Baseline.* O-COCOSDA 2017. ([arXiv:1709.05522](https://arxiv.org/abs/1709.05522))
- **AISHELL-3** ([OpenSLR-93](https://www.openslr.org/93/)) — 218 spk → contributes to `stats_zh.json` v0.2.0.
  Shi, Y., Bu, H., Xu, X., Zhang, S., & Li, M. (2021). *AISHELL-3: A Multi-Speaker Mandarin TTS Corpus.* Interspeech 2021. ([ISCA archive](https://www.isca-archive.org/interspeech_2021/shi21c_interspeech.html))
- **Common Voice — Mozilla Data Collective, Scripted Speech 25.0 (fr)** — 2026-03-09 dump, 984F + 3793M speakers → `stats_fr.json` v0.1.0.
  Ardila, R., Branson, M., Davis, K., Kohler, M., Meyer, J., Henretty, M., Morais, R., Saunders, L., Tyers, F., & Weber, G. (2020). *Common Voice: A Massively-Multilingual Speech Corpus.* LREC 2020, 4218–4222. ([ACL Anthology](https://aclanthology.org/2020.lrec-1.520/)) — [dataset](https://mozilladatacollective.com/) (CC0-1.0)

For the full training protocol (sampling, holdout splits, weight search), see [`voiceya/sidecars/visualizer-backend/CHANGELOG_ZH.md`](./voiceya/sidecars/visualizer-backend/CHANGELOG_ZH.md) and [`CHANGELOG_FR.md`](./voiceya/sidecars/visualizer-backend/CHANGELOG_FR.md).

### Vendored components

- [**gender-voice-visualization**](https://github.com/guojunximi-cell/gender-voice-visualization) — Engine C sidecar source (`working-chinese-version` branch); see [`voiceya/sidecars/README.md`](./voiceya/sidecars/README.md) for the rsync sync protocol.
- [**k3-cat/inaSpeechSegmenter**](https://github.com/k3-cat/inaSpeechSegmenter) — K-3 / TensorFlow 2 compatibility fork of inaSpeechSegmenter, included as a git submodule.

### Frontend libraries

Source code is released under **MPL-2.0**. See [`LICENSE`](./LICENSE).

See [`LICENSE`](./LICENSE).
