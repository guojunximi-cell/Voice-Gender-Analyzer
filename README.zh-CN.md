**简体中文** | [English](./README.md)

# 声音分析鸭

> 在一个页面查看音素对齐的 F0 和共鸣，辅以神经网络判断作为参考。作者希望它能辅助声音训练。

[![license](https://img.shields.io/badge/license-MPL--2.0-green)](./LICENSE)
[![python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![node](https://img.shields.io/badge/node-%E2%89%A520-green)](https://nodejs.org/)

---

# 架构

```
浏览器 POST /analyze-voice
  └─ routers/api.py           → 文件 / 时长校验，analyse_voice.kiq()
       └─ Redis Stream         → taskiq broker (RedisStreamBroker)
            └─ worker 进程     → voiceya/tasks/analyser.py::analyse_voice
                 └─ services/audio_analyser/__init__.py::do_analyse
                      ├─ Engine A: do_segmentation()
                      └─ Engine C: run_engine_c()

浏览器 GET /status/{task_id}  (Accept: text/event-stream)
  └─ subscribe_to_events_and_generate_sse()
       └─ Redis XREAD（流式回放）
```

## 本地开发

需要 **Python 3.13** · [Node.js ≥ 20](https://nodejs.org/)（带 pnpm）· [uv](https://docs.astral.sh/uv/) · 本地 Redis。

```bash
git clone --recurse-submodules https://github.com/guojunximi-cell/Voice-Gender-Analyzer.git
cd Voice-Gender-Analyzer
uv sync                 # 按 uv.lock 装 Python 依赖到 .venv
pnpm install -C web     # 前端依赖
python run_app.py       # 一键起 redis + uvicorn + taskiq worker + vite
```

`run_app.py` 会并发拉起四个进程，并打开 <http://localhost:5173>

## Engine C

Engine C 跑在独立的 sidecar 容器里，与 API、worker 协同。

```bash
cp .env.example .env              # 改 ENGINE_C_ENABLED=true
docker compose --profile engine-c up -d --build
```

## Docker 

```bash
cp .env.example .env
docker compose --profile engine-c up -d --build    # 完整管线（A + C）
# 不带 Engine C sidecar（仅 Engine A）：
docker compose up -d --build
```

## API

```http
POST /analyze-voice
Content-Type: multipart/form-data

file:     <音频 blob，≤ MAX_FILE_SIZE_MB，≤ MAX_AUDIO_DURATION_SEC 秒>
language: zh-CN | en-US           # 可选，默认 zh-CN
script:   <可选稿子 — 在 Engine C 中绕开 ASR>
```

```http
GET /status/{task_id}
Accept: text/event-stream
```

## 配置

详见 [`.env.example`](./.env.example) 与 `voiceya/config.py`

## Railway 部署

详见 [`docs/RAILWAY_DEPLOY.md`](./docs/RAILWAY_DEPLOY.md)


## 已下线

**Engine B** （`voiceya/services/audio_analyser/acoustic_analyzer.py`）

## 引用

### 模型 / 对齐器 / 工具包

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
  Boersma, P., & Weenink, D. (2026). *Praat: doing phonetics by computer* [Computer program]. Version 6.4.65. — [praat.org](https://www.fon.hum.uva.nl/praat/) ([引用规范](https://www.fon.hum.uva.nl/praat/manual/FAQ__How_to_cite_Praat.html))

### 预训练 MFA 声学模型 & 词典

- `mandarin_mfa` v2.0.0 —— `zh-CN`
- `english_us_arpa` —— `en-US`
- `french_mfa` —— `fr-FR`

### 构建 `stats_*.json`训练语料 

- **AISHELL-1**（[OpenSLR-33](https://www.openslr.org/33/)）—— 400 说话人 → 入 `stats_zh.json` v0.2.0。
  Bu, H., Du, J., Na, X., Wu, B., & Zheng, H. (2017). *AISHELL-1: An Open-Source Mandarin Speech Corpus and a Speech Recognition Baseline.* O-COCOSDA 2017.
- **AISHELL-3**（[OpenSLR-93](https://www.openslr.org/93/)）—— 218 说话人 → 入 `stats_zh.json` v0.2.0。
  Shi, Y., Bu, H., Xu, X., Zhang, S., & Li, M. (2021). *AISHELL-3: A Multi-Speaker Mandarin TTS Corpus.* Interspeech 2021. ([ISCA archive](https://www.isca-archive.org/interspeech_2021/shi21c_interspeech.html))
- **Common Voice —— Mozilla Data Collective, Scripted Speech 25.0 (fr)** —— 2026-03-09 dump，984F + 3793M 说话人 → `stats_fr.json` v0.1.0。
  Ardila, R., Branson, M., Davis, K., Kohler, M., Meyer, J., Henretty, M., Morais, R., Saunders, L., Tyers, F., & Weber, G. (2020). *Common Voice: A Massively-Multilingual Speech Corpus.* LREC 2020, 4218–4222. ([ACL Anthology](https://aclanthology.org/2020.lrec-1.520/)) —— [数据集](https://mozilladatacollective.com/)（CC0-1.0）

完整训练协议见 [`voiceya/sidecars/visualizer-backend/CHANGELOG_ZH.md`](./voiceya/sidecars/visualizer-backend/CHANGELOG_ZH.md) 与 [`CHANGELOG_FR.md`](./voiceya/sidecars/visualizer-backend/CHANGELOG_FR.md)。

### Vendored 组件

- [**gender-voice-visualization**](https://github.com/guojunximi-cell/gender-voice-visualization) —— Engine C sidecar 源码（`working-chinese-version` 分支）；rsync 同步流程见 [`voiceya/sidecars/README.md`](./voiceya/sidecars/README.md)。
- [**k3-cat/inaSpeechSegmenter**](https://github.com/k3-cat/inaSpeechSegmenter) —— inaSpeechSegmenter 的 K-3 / TensorFlow 2 兼容 fork，作为 git submodule 引入。

### 前端库

[Vite](https://vitejs.dev/) · [WaveSurfer.js](https://wavesurfer.xyz/) · [uPlot](https://github.com/leeoniya/uPlot)

## 协议 & 声明

详见 [`LICENSE`](./LICENSE)

