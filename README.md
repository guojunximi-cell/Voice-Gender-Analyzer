# 声音分析鸭 — Voice Gender Analyzer

基于深度学习 + 声学特征 + 音素级强制对齐的浏览器端中文语音性别分析工具。上传 / 录制一段最长 3 分钟的音频，在一个页面里读懂它的性别表达、基频、共振峰与音素粒度的声学细节。

![license](https://img.shields.io/badge/license-MPL--2.0-green) ![python](https://img.shields.io/badge/python-3.13-blue) ![node](https://img.shields.io/badge/node-%E2%89%A520-green)

## 功能

* **三引擎并存的分析管线**
  * Engine A — inaSpeechSegmenter（k3-cat fork）做 VAD 与男声/女声/音乐/噪声分段
  * Engine B — 仓内自研 LPC 共振峰估计 + 合成性别评分
  * Engine C — FunASR Paraformer-zh 转写 → MFA 强制对齐 → Praat 共振峰 → 音素级 z-score（可选，默认关）
* **交互式可视化**
  * 波形 + 男声/女声色带 + 可点击段片段
  * 三行 "三明治" 时间线：上行基频热图 / 中行汉字卡拉 OK / 下行共鸣热图，逐字等宽对齐
  * 基频范围 p5~p95 磨砂胶囊 + 性别谱条，同一视觉语言
  * 整文件指标面板：均值 / 中位数 / 标准差 / 性别比例
* **历史会话**
  * IndexedDB 持久化 50 条会话 + 500 MB 原始音频（LRU），刷新后仍在
  * 性别比例散点图支持按 Engine A / 基频 / 共鸣 三种标签源切换

## 技术栈

| 层次 | 组件 |
|-|-|
| 前端 | Vanilla JS · Vite · WaveSurfer.js · uPlot |
| 后端 | Python 3.13 · FastAPI · Uvicorn · Taskiq · Redis |
| Engine A | [inaSpeechSegmenter](https://github.com/k3-cat/inaSpeechSegmenter) (Keras 3 / TensorFlow 2) |
| Engine B | librosa · scipy（仓内自研） |
| Engine C | [FunASR](https://github.com/modelscope/FunASR) · [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) · [Praat](https://www.fon.hum.uva.nl/praat/) · [gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization) sidecar |
| 部署 | Docker Compose · Railway |

## 本地开发

需要 **Python 3.13** · [Node.js ≥ 20](https://nodejs.org/)（带 pnpm）· [uv](https://docs.astral.sh/uv/) · 本地 Redis。

```bash
git clone --recurse-submodules https://github.com/guojunximi-cell/Voice-Gender-Analyzer.git
cd Voice-Gender-Analyzer
uv sync                 # 按 uv.lock 装 Python 依赖到 .venv
pnpm install -C web     # 前端依赖
python run_app.py       # 一键起 redis + uvicorn + taskiq worker + vite
```

`run_app.py` 会并发拉起四个进程；默认访问 <http://localhost:5173>（vite 把 API 请求代理到 :8080）。

### 启用 Engine C（可选）

Engine C 依赖一个独立的 sidecar 容器，不默认启动。

```bash
cp .env.example .env              # 改 ENGINE_C_ENABLED=true
docker compose --profile engine-c up -d --build
```

首次构建会下载 FunASR + MFA mandarin_mfa 模型 ≈ 2.5 GB，耗时 10 分钟左右；之后启动秒级。失败或 sidecar 不可达时，`summary.engine_c = null`，Engine A/B 结果正常返回。

## Docker 自建（VPS / 自托管）

```bash
cp .env.example .env
docker compose up -d --build            # 仅 Engine A/B
# 或
docker compose --profile engine-c up -d --build   # 含 Engine C sidecar
```

服务监听 `http://localhost:8080`。首次构建约 10 ~ 15 分钟（TensorFlow + inaSpeechSegmenter 模型较大）。可配置字段见 `.env.example`。

## Railway 部署

两条路径，任选其一，详见 `docs/RAILWAY_DEPLOY.md`：

* **CLI bootstrap**：`bash scripts/railway-bootstrap.sh`，脚本幂等地创建 app + worker + Redis（可选 + Engine C sidecar）并接好变量引用。
* **UI 手动**：Railway → New Project → Deploy from GitHub → 加 Redis → 填 `REDIS_URL = ${{Redis.REDIS_URL}}`。

> 建议 ≥ 1 GB 内存 / service。Engine C sidecar 单独走 `railway.sidecar.toml`，需要 ≥ 4 GB 才能稳定跑 MFA。

## 核心环境变量

| 变量 | 默认 | 说明 |
|-|-|-|
| `REDIS_URL` | — | Taskiq 任务队列与 SSE 事件总线，必填 |
| `MAX_FILE_SIZE_MB` | 10 | 单次上传上限 |
| `MAX_AUDIO_DURATION_SEC` | 180 | 超时音频会 400 拒绝 |
| `MAX_CONCURRENT` | 2 | Taskiq worker 并发任务数 |
| `ENGINE_C_ENABLED` | false | 总开关；关闭时连 FunASR 都不会 import |
| `ENGINE_C_SIDECAR_URL` | `http://visualizer-backend:8001` | worker → sidecar 内网地址 |
| `ENGINE_C_SIDECAR_TOKEN` | 空 | worker / sidecar 共享 bearer；生产请务必设置 |
| `ENGINE_C_MFA_BEAM` | 50 | MFA 主 beam（上游 100，narrower = faster） |
| `ENGINE_C_MFA_RETRY_BEAM` | 200 | MFA 回退 beam（上游 400） |
| `ENGINE_C_ASR_CACHE_SIZE` | 64 | FunASR 转写结果 LRU 条数（SHA-256 键） |

完整清单见 `.env.example` 与 `voiceya/config.py`。

## 代码结构

```
voiceya/                        # 后端主包
├── routers/api.py              # FastAPI 路由（SSE 事件流在 services/sse.py）
├── services/
│   ├── audio_analyser/
│   │   ├── engine_a.py         # VAD + 性别分段（inaSpeechSegmenter）
│   │   ├── acoustic_analyzer.py# Engine B：LPC 共振峰 + 合成评分
│   │   ├── engine_c.py         # Engine C 编排（ASR → sidecar）
│   │   └── engine_c_asr.py     # FunASR Paraformer-zh（带 SHA-256 LRU 缓存）
│   ├── sse.py / events_stream.py
│   └── ...
├── sidecars/
│   ├── visualizer-backend/     # vendor 自 gender-voice-visualization
│   ├── wrapper/main.py         # FastAPI 薄壳 + MFA 参数 patch
│   └── visualizer-backend.Dockerfile
├── inaSpeechSegmenter/         # git submodule → k3-cat/inaSpeechSegmenter
├── taskiq.py                   # Worker broker
└── config.py                   # Pydantic Settings
web/
├── src/
│   ├── main.js                 # 入口，IndexedDB + SSE + 整体编排
│   └── modules/                # UI 组件（heatmap-band, metrics-panel, waveform…）
└── ...
docker-compose.yml              # app + worker + redis (+ engine-c profile)
railway.toml / railway.sidecar.toml
```

## 规范

* Python — Ruff（`.ruff.toml`：py313、双引号、snake_case、LF）
* 前端 — oxlint + Prettier（tabs、120 列、camelCase、import 排序）
* EditorConfig 覆盖全语言缩进 / 换行
* vendor 目录（`voiceya/inaSpeechSegmenter/`、`voiceya/sidecars/visualizer-backend/`）不接受替换或重置，上游同步走 `voiceya/sidecars/README.md` 的 rsync 步骤

## 致谢

* [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter) — Doukhan et al., ICASSP 2018（MIT）
* [k3-cat/inaSpeechSegmenter](https://github.com/k3-cat/inaSpeechSegmenter) — Keras 3 兼容 fork
* [FunASR](https://github.com/modelscope/FunASR) — Paraformer-zh ASR（Apache-2.0）
* [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) — 强制对齐（MIT）
* [gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization) — Engine C sidecar 源
* [WaveSurfer.js](https://wavesurfer.xyz/) · [uPlot](https://github.com/leeoniya/uPlot)

## 协议 & 声明

源码采用 **MPL-2.0**。本工具仅用于学术研究与语音技术学习目的；性别分析结果基于统计声学模型，**不代表对个体性别身份的判断**。
