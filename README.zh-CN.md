**简体中文** | [English](./README.md)

# 声音分析鸭 · Voice Gender Analyzer

> 浏览器端的短音频性别 / 声学 / 音素级分析工具，背后是深度学习 VAD + 强制对齐。上传 / 录制最长 3 分钟的音频，在一个页面里读懂它的性别表达、基频、共振峰与音素粒度的声学细节。

[![license](https://img.shields.io/badge/license-MPL--2.0-green)](./LICENSE)
[![python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![node](https://img.shields.io/badge/node-%E2%89%A520-green)](https://nodejs.org/)

---

## 功能

- **多引擎分析管线**
  - **Engine A — k-3**（基于 [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter)，[k3-cat fork](https://github.com/k3-cat/inaSpeechSegmenter)）：VAD + 男声 / 女声 / 音乐 / 噪声分段
  - **Engine C**（feature-flagged）：ASR → [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) → [Praat](https://www.fon.hum.uva.nl/praat/) 共振峰 → 音素级 z-score
- **双语 ASR（Engine C）**
  - `zh-CN` — [FunASR](https://github.com/modelscope/FunASR) Paraformer-zh
  - `en-US` — [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（默认 `base.en`，可选 `tiny / small / medium`）
- **交互式可视化**
  - 波形 + 男声 / 女声色带 + 可点击段片段
  - 三行"三明治"时间线：上行基频热图 / 中行汉字（或单词）卡拉 OK / 下行共鸣热图，逐字等宽对齐
  - 基频范围 p5~p95 磨砂胶囊 + 性别谱条，统一视觉语言
  - 整文件指标面板：均值 / 中位数 / 标准差 / 性别比例
- **历史会话**
  - IndexedDB 持久化 50 条会话 + 500 MB 原始音频（LRU），刷新仍在
  - 性别比例散点图支持按 Engine A / 基频 / 共鸣 三种标签源切换

## 技术栈

| 层次 | 组件 |
|---|---|
| 前端 | Vanilla JS · [Vite](https://vitejs.dev/) · [WaveSurfer.js](https://wavesurfer.xyz/) · [uPlot](https://github.com/leeoniya/uPlot) |
| 后端 | Python 3.13 · [FastAPI](https://fastapi.tiangolo.com/) · [Uvicorn](https://www.uvicorn.org/) · [Taskiq](https://taskiq-python.github.io/) · [Redis](https://redis.io/) |
| Engine A | [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter)（Keras 3 / TensorFlow 2），[k3-cat fork](https://github.com/k3-cat/inaSpeechSegmenter) |
| Engine C | [FunASR](https://github.com/modelscope/FunASR) · [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) · [Praat](https://www.fon.hum.uva.nl/praat/) · [gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization) sidecar |
| 部署 | Docker Compose · [Railway](https://railway.app/) |

## 本地开发

需要 **Python 3.13** · [Node.js ≥ 20](https://nodejs.org/)（带 pnpm）· [uv](https://docs.astral.sh/uv/) · 本地 Redis。

```bash
git clone --recurse-submodules https://github.com/guojunximi-cell/Voice-Gender-Analyzer.git
cd Voice-Gender-Analyzer
uv sync                 # 按 uv.lock 装 Python 依赖到 .venv
pnpm install -C web     # 前端依赖
python run_app.py       # 一键起 redis + uvicorn + taskiq worker + vite
```

`run_app.py` 会并发拉起四个进程，并自动打开 <http://localhost:5173>（Vite 把 API 请求代理到 `:8080`）。

### 常用命令

```bash
# 仅后端（不起 Vite）
python -m voiceya

# 仅 worker
python -m taskiq worker voiceya.taskiq:broker voiceya.tasks.analyser --workers 1 --log-level INFO

# 前端生产构建
pnpm --filter ./web run build

# Lint & format
ruff check . && ruff format .
pnpm --filter ./web run lint
pnpm --filter ./web run fmt:fix

# 测试（无 pytest 依赖，直接 python 跑）
python tests/test_chunker.py
python tests/test_multichunk_merge.py
```

## Engine C（可选）

Engine C 跑在独立的 sidecar 容器里，**默认关闭**。

```bash
cp .env.example .env              # 改 ENGINE_C_ENABLED=true
docker compose --profile engine-c up -d --build
```

首次构建会下载 FunASR 权重 + MFA `mandarin_mfa` 模型（≈ 2.5 GB，约 10 分钟），之后启动秒级。失败或 sidecar 不可达时，`summary.engine_c = null`，Engine A 结果不受影响。

Sidecar 源码 vendor 自 [guojunximi-cell/gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization)，放在 `voiceya/sidecars/visualizer-backend/` 下；FastAPI 薄壳在 `voiceya/sidecars/wrapper/main.py`。upstream 同步走 [`voiceya/sidecars/README.md`](./voiceya/sidecars/README.md) 的 rsync 步骤。

### 单独构建 sidecar 镜像

```bash
docker build -f voiceya/sidecars/visualizer-backend.Dockerfile -t voiceya-engine-c:dev .
docker run --rm -p 8001:8001 voiceya-engine-c:dev
curl http://localhost:8001/healthz
```

## Docker 自建（VPS / 自托管）

```bash
cp .env.example .env
docker compose up -d --build                       # 仅 Engine A
# 或，含 Engine C：
docker compose --profile engine-c up -d --build
```

服务监听 `http://localhost:8080`。首次构建 10 ~ 15 分钟（TensorFlow + inaSpeechSegmenter 模型较大）。可配置字段见 `.env.example`。

## Railway 部署

两条路径，详见 [`docs/RAILWAY_DEPLOY.md`](./docs/RAILWAY_DEPLOY.md)：

- **CLI bootstrap** —— `bash scripts/railway-bootstrap.sh`，幂等地创建 app + worker + Redis（可选 + Engine C sidecar）并接好变量引用。
- **UI 手动** —— Railway → New Project → Deploy from GitHub → 加 Redis → 填 `REDIS_URL = ${{Redis.REDIS_URL}}`。

> 建议每个 service ≥ 1 GB 内存。Engine C sidecar 单独走 `railway.sidecar.toml`，需要 ≥ 4 GB 才能稳定跑 MFA。

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

`language` 字段决定 Engine C 的路由：`zh-CN` → FunASR Paraformer-zh + `mandarin_mfa` + `stats_zh.json`；`en-US` → faster-whisper + `english_us_arpa` + `stats.json`。Script 模式两种语言通用，绕开 ASR 直接用前端稿子。

状态接口走 Redis Streams（不是 pub/sub），迟到的客户端能从头回放事件。

## 配置

完整清单见 [`.env.example`](./.env.example) 与 `voiceya/config.py`。

| 变量 | 默认 | 说明 |
|---|---|---|
| `REDIS_URL` | — | Taskiq 任务队列与 SSE 事件总线（必填） |
| `MAX_FILE_SIZE_MB` | 10 | 单次上传上限 |
| `MAX_AUDIO_DURATION_SEC` | 180 | 超时音频会被 HTTP 400 拒绝 |
| `MAX_CONCURRENT` | 2 | Taskiq worker 并发任务数 |
| `MAX_QUEUE_DEPTH` | 30 | 队列回压阈值 |
| `RATE_LIMIT_CT` | 10 | 单窗口允许请求数 |
| `RATE_LIMIT_DURATION_SEC` | 60 | 限流窗口 |
| `TASK_MAX_EXEC_SEC` | 900 | 单任务执行上限 |
| `ENGINE_C_ENABLED` | `false` | 总开关；为 `false` 时 FunASR 都不会 import |
| `ENGINE_C_SIDECAR_URL` | `http://visualizer-backend:8001` | worker → sidecar 内网地址 |
| `ENGINE_C_SIDECAR_TOKEN` | 空 | worker / sidecar 共享 bearer；生产请务必设置 |
| `ENGINE_C_SIDECAR_TIMEOUT_SEC` | 60 | 单次 HTTP 请求超时 |
| `ENGINE_C_MIN_DURATION_SEC` | 3 | 短于此长度的音频跳过 Engine C |
| `ENGINE_C_MAX_AUDIO_MB` | 50 | Sidecar 单请求音频字节上限（防御内部 DoS） |
| `ENGINE_C_WHISPER_MODEL` | `base.en` | faster-whisper 模型 ID（`tiny.en` / `small.en` / `medium.en`） |
| `ENGINE_C_WHISPER_DEVICE` | `auto` | `auto` 有 CUDA 用 CUDA，否则 CPU |
| `ENGINE_C_WHISPER_COMPUTE_TYPE` | `int8` | CT2 计算类型；CPU 上 `int8` 平衡速度 / 体积 |

## 架构

```
浏览器 POST /analyze-voice
  └─ routers/api.py           → 文件 / 时长校验，analyse_voice.kiq()
       └─ Redis Stream         → taskiq broker (RedisStreamBroker)
            └─ worker 进程     → voiceya/tasks/analyser.py::analyse_voice
                 └─ services/audio_analyser/__init__.py::do_analyse
                      ├─ Engine A: do_segmentation()
                      └─ Engine C: run_engine_c()  (feature-flagged)

浏览器 GET /status/{task_id}  (Accept: text/event-stream)
  └─ subscribe_to_events_and_generate_sse()
       └─ Redis XREAD（流式回放，迟到客户端能看到全部事件）
```

API 进程与 worker 进程是分离的：**API 不加载 TensorFlow 模型**（省 ~500 MB），只做任务分发与 SSE 转发；`load_seg()` 只在 `broker.is_worker_process` 为真时触发。

## 代码结构

```
voiceya/                           后端主包
├── routers/api.py                 FastAPI 路由（SSE 在 services/sse.py）
├── services/
│   ├── audio_analyser/
│   │   ├── engine_a.py            VAD + 性别分段（k-3）
│   │   ├── engine_c.py            Engine C 编排（ASR → sidecar）
│   │   ├── engine_c_asr.py        FunASR Paraformer-zh（带 SHA-256 LRU 缓存）
│   │   ├── engine_c_asr_en.py     faster-whisper，返回 word_timestamps
│   │   └── acoustic_analyzer.py   Engine B（已下线，见下方）
│   ├── sse.py / events_stream.py  SSE 事件总线
│   └── ...
├── sidecars/
│   ├── visualizer-backend/        vendor 自 gender-voice-visualization
│   ├── wrapper/main.py            FastAPI 薄壳 + MFA 参数 patch
│   └── visualizer-backend.Dockerfile
├── inaSpeechSegmenter/            git submodule → k3-cat/inaSpeechSegmenter
├── taskiq.py                      worker broker
└── config.py                      Pydantic Settings
web/
├── src/
│   ├── main.js                    入口：IndexedDB + SSE + 整体编排
│   └── modules/                   UI 组件（heatmap-band, metrics-panel, waveform, ...）
└── ...
docker-compose.yml                 app + worker + redis (+ engine-c profile)
railway.toml / railway.sidecar.toml
```

## 已下线

**Engine B** —— LPC 共振峰 + 合成性别评分（`voiceya/services/audio_analyser/acoustic_analyzer.py`）。自 **2026-04-07** 起结果不再对外暴露，但代码保留在仓库里供参考、也方便后续复活多引擎对比。

## 规范

- **Python** —— Ruff（`.ruff.toml`：py313、双引号、snake_case、LF）
- **前端** —— oxlint + Prettier（tabs、120 列、camelCase、import 排序）
- **EditorConfig** —— 覆盖全语言缩进 / 换行
- **vendor 目录**（`voiceya/inaSpeechSegmenter/`、`voiceya/sidecars/visualizer-backend/`）不接受替换或重置；upstream 同步走 [`voiceya/sidecars/README.md`](./voiceya/sidecars/README.md) 的 rsync 步骤
- **分支** —— 英文相关在 `dev-en`；合 `main` 需显式授权，不跨分支 cherry-pick

## 致谢

- [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter) —— Doukhan et al., ICASSP 2018（MIT）
- [k3-cat/inaSpeechSegmenter](https://github.com/k3-cat/inaSpeechSegmenter) —— Keras 3 兼容 fork
- [FunASR](https://github.com/modelscope/FunASR) —— Paraformer-zh ASR（Apache-2.0）
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) —— CTranslate2 Whisper 推理（MIT）
- [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) —— 强制对齐（MIT）
- [gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization) —— Engine C sidecar 源
- [WaveSurfer.js](https://wavesurfer.xyz/) · [uPlot](https://github.com/leeoniya/uPlot)

## 协议 & 声明

源码采用 **MPL-2.0**，详见 [`LICENSE`](./LICENSE)。

本工具仅用于学术研究与语音技术学习目的；性别分析结果基于统计声学模型，**不代表对个体性别身份的判断**。
