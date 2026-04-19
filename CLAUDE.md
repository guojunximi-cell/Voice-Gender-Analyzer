# 代码库速览

- 栈：Python 3.13 (FastAPI + Taskiq + Redis) + Vanilla JS/Vite 前端 + inaSpeechSegmenter 子模块（k3-cat fork）
- 入口：voiceya.main:app（API+静态托管）、voiceya.taskiq:broker（Worker）、web/src/main.js
- 部署：Dockerfile 多阶段 (Node→Python→Alpine)，需 Redis 与独立 Worker 服务
- 规范工具：Ruff（py313，双引号、LF）、oxlint + Prettier（tabs、120 列）、EditorConfig

# 分析管线：三引擎并存

| 引擎 | 文件 | 职责 | 依赖 |
|------|------|------|------|
| Engine A | `voiceya/services/audio_analyser/engine_a.py` | VAD + 性别分段（inaSpeechSegmenter） | Keras/TF |
| Engine B | `voiceya/services/audio_analyser/acoustic_analyzer.py` | LPC 共振峰 + 合成性别评分（仓内自研） | librosa/scipy |
| Engine C | `voiceya/services/audio_analyser/engine_c.py` + sidecar | FunASR ASR → MFA 对齐 → Praat 共振峰 → 音素级 z-score（**feature-flagged**） | funasr + visualizer-backend sidecar |

Engine C 默认关闭（`ENGINE_C_ENABLED=false`）；开启需同时起 sidecar：
`docker compose --profile engine-c up -d --build`。失败/不可达时 `summary.engine_c = null`，不影响 A/B 结果。

Sidecar 源码 vendor 自 [guojunximi-cell/gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization.git)
（working-chinese-version，同步 2026-04-16 @ 446f124），放在 `voiceya/sidecars/visualizer-backend/`，
FastAPI 薄壳在 `voiceya/sidecars/wrapper/main.py`。

# 协作约束（自我框架）

1. 分支纪律：默认在 public-beta；合 main 需显式授权，不跨分支 cherry-pick。
2. 子模块/vendor 谨慎：`voiceya/inaSpeechSegmenter`（k3-cat fork）和 `voiceya/sidecars/visualizer-backend/`
   （gender-voice-visualization zh 分支）都是以文件形式 vendor 进仓库的——不替换、不重置，只在明确要求时才动；
   upstream 升级走 `voiceya/sidecars/README.md` 里的 rsync 步骤。
3. 风格一致：Python 遵 .ruff.toml（双引号、snake_case）；JS 遵 .prettierrc（tabs、camelCase、import sort）。编辑前先读周边文件匹配风格。
4. 接口边界：FastAPI 路由只走 routers/api.py；SSE 事件结构在 services/sse.py 定义，改字段需前后端同步。
   Engine C 产出的 `summary.engine_c` 是可选字段，前端未消费前后端都可独立迭代。
5. 部署构型：Dockerfile 已跑通 Railway；docker-compose.yml 是 VPS 通用路径（含 `engine-c` profile）。
   改 Docker 前先本地 `docker compose up --build` 验证。Engine C sidecar 镜像 ~2.5 GB，首次构建下载 MFA 模型耗时可达 10 分钟。
6. 禁区：不动 .venv/、不 git add -A、不 --no-verify。
7. 高风险操作一律先确认：删文件、改 CI、动提交历史、推远端、升/降依赖。
