# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 开发命令

```bash
# 本地全栈启动（uvicorn + taskiq worker + vite + 自动开浏览器）
python run_app.py            # 或 uv run python run_app.py

# 仅后端（不起 vite）
python -m voiceya            # API 进程，127.0.0.1:8080

# 仅 worker
python -m taskiq worker voiceya.taskiq:broker voiceya.tasks.analyser --workers 1 --log-level INFO

# 前端开发
pnpm --filter ./web run dev
pnpm --filter ./web run build   # 生产构建到 web/dist/

# Python lint & format
ruff check .
ruff format .

# JS lint & format
pnpm --filter ./web run lint        # oxlint
pnpm --filter ./web run fmt:fix     # prettier --write

# 测试（无 pytest 依赖，直接 python 跑）
python tests/test_chunker.py           # 纯 stdlib，无音频依赖
python tests/test_multichunk_merge.py  # 依赖 cmudict.txt，需先 cd visualizer-backend 或测试脚本自己 chdir

# Engine C sidecar 本地镜像（独立容器）
docker build -f voiceya/sidecars/visualizer-backend.Dockerfile -t voiceya-engine-c:dev .
docker run --rm -p 8001:8001 voiceya-engine-c:dev
curl http://localhost:8001/healthz

# 全栈 Docker（含 sidecar）
docker compose --profile engine-c up -d --build
```

## 代码库速览

- 栈：Python 3.13 (FastAPI + Taskiq + Redis) + Vanilla JS/Vite 前端 + inaSpeechSegmenter 子模块（k3-cat fork）
- 入口：`voiceya.main:app`（API+静态托管）、`voiceya.taskiq:broker`（Worker）、`web/src/main.js`
- 部署：Dockerfile 多阶段 (Node→Python→Alpine)，需 Redis 与独立 Worker 服务
- 规范工具：Ruff（py313，双引号、LF）、oxlint + Prettier（tabs、120 列）、EditorConfig

## 请求生命周期

```
浏览器 POST /analyze-voice
  └─ routers/api.py          → 文件校验、时长检查、analyse_voice.kiq()
       └─ Redis Stream        → taskiq broker（RedisStreamBroker）
            └─ worker 进程    → voiceya/tasks/analyser.py::analyse_voice
                 └─ services/audio_analyser/__init__.py::do_analyse
                      ├─ Engine A: do_segmentation()
                      └─ Engine C: run_engine_c()（feature-flagged）

浏览器 GET /status/{task_id}  （Accept: text/event-stream）
  └─ subscribe_to_events_and_generate_sse()
       └─ Redis XREAD（流式回放，支持迟到连接）
```

API 进程与 worker 进程是分离的：**API 不加载 TF 模型**（省 ~500 MB），只做任务分发与 SSE 转发；`load_seg()` 只在 `broker.is_worker_process` 时触发。SSE 事件用 Redis Streams（非 pub/sub），迟到的客户端能从头回放。

## 分析管线：A + C 双引擎

| 引擎 | 文件 | 职责 | 依赖 |
|------|------|------|------|
| Engine A | `voiceya/services/audio_analyser/engine_a.py` | VAD + 性别分段（inaSpeechSegmenter） | Keras/TF |
| Engine C | `voiceya/services/audio_analyser/engine_c.py` + sidecar | ASR → MFA 对齐 → Praat 共振峰 → 音素级 z-score（**feature-flagged**） | funasr + faster-whisper + visualizer-backend sidecar |

Engine B（`acoustic_analyzer.py`，LPC 共振峰 + 合成性别评分）2026-04-07 下线，
代码已删除。`summary.overall_f0_median_hz` 现在来自 `f0_panel.py`（pyin[60-250]，
advice_v2 与 do_statics 共用一次结果）；`summary.overall_gender_score` 改由
`statics._femininity_score()` 从 Engine A 的置信度 + label 推导。

Engine C 默认关闭（`ENGINE_C_ENABLED=false`）；开启需同时起 sidecar：
`docker compose --profile engine-c up -d --build`。失败/不可达时 `summary.engine_c = null`，不影响 Engine A 结果。

## Advice v2 输出 schema

`summary.advice` 是测量 + 倾向并列展示，不出 verdict。来源：`voiceya/services/audio_analyser/advice_v2.py`（纯函数）+ `f0_panel.py`（pyin[60-250] + voiced_flag）。结构：

- `f0_panel`：F0 中位数、p25/p75、voiced_duration_sec、`range_zone_key`（5 档：low / mid_lower / mid_neutral / mid_upper / high）、reliability。
- `tone_panel`：ina 五档倾向（`leans_*` ≥ 0.78 / `weakly_*` ≥ 0.50 / `not_clearly_leaning`），帧标签分布，永久 `caveat_key`。`weakly_*` 是低置信度方向信号，避免在 0.5–0.78 区间把方向信息丢掉。
- `summary_panel`：< 50 字模板文案，按 `{zone}_{tendency}` 派生 i18n key。
- `gating_tier`：`minimal` (<10s) / `standard` (10–30s) / `full` (≥30s)。minimal 不出 tone/summary。

设计与决策依据见 `docs/plans/v2_redesign_measurement.md`；`tests/reports/advice_v2_render_<date>.md` 为 95 样本回归基线。

## Engine C 详细流程

```
run_engine_c()                              # engine_c.py
  ├─ free mode zh: transcribe_zh()          # engine_c_asr.py — FunASR Paraformer-zh（LRU 缓存 SHA-256 键）
  ├─ free mode en: transcribe_en()          # engine_c_asr_en.py — faster-whisper，返回 word_timestamps
  └─ script mode: 跳过 ASR，直接用稿子
       └─ POST /engine_c/analyze → sidecar  # wrapper/main.py（含认证 token）
            ├─ ffmpeg silencedetect
            ├─ 英文 + word_timestamps → chunker.plan_chunks() → 多块并行 MFA
            │   └─ PreloadedAligner.align_one()   # kalpy，startup 从 40s→亚秒级
            └─ 中文 / 无时间戳 → preprocessing.process()（vendored，subprocess MFA）
                 ├─ 子进程 shim 替换 preprocessing.subprocess          # 不改 vendor 文件
                 │   调整 --beam/--retry_beam 并把 english_mfa→english_us_arpa
                 └─ phones.parse() → resonance.compute_resonance()
```

**多语支持**：请求在 `POST /analyze-voice` 带 `language` 字段（`zh-CN` | `en-US` | `fr-FR` | `ko-KR`，默认 `zh-CN`）。
- `zh-CN`：free mode 走 FunASR Paraformer-zh；sidecar 用 `mandarin_mfa` + `stats_zh.json`。
- `en-US`：free mode 走 faster-whisper（默认 `base.en`，env `ENGINE_C_WHISPER_MODEL` 可切 tiny/small/medium）；sidecar 用 `english_us_arpa` + `stats.json`。
- `fr-FR`：free mode 走 faster-whisper multilingual（默认 `base`，env `ENGINE_C_WHISPER_MODEL_FR`，`language="fr"` pin decode）；sidecar 用 `french_mfa` + `stats_fr.json` + `weights_fr.json`。fr 上线由 sidecar 启动时检测 `stats_fr.json` 是否存在决定——缺则 `/healthz` 不广告 `fr`，worker 收 503 → `engine_c=null` 优雅降级，Engine A 仍正常。
- `ko-KR`：free mode 走 faster-whisper multilingual（默认 `base`，env `ENGINE_C_WHISPER_MODEL_KO`，`language="ko"` pin decode）；ASR 清洗只保留 Hangul precomposed 音节 + 空白，drop Latin / Jamo / 数字（MFA `korean_mfa` 字典纯 Hangul，loanword 会 OOV）。sidecar 用 `korean_mfa` 声学 + 字典 + `stats_ko.json` + `weights_ko.json`。同 fr 优雅降级。ko 暂未进 `_ADAPTIVE_LANGS`——等 `stats_ko.json` 训完确认 5500 Hz baseline 才打开 adaptive ceiling。
- script mode 四种语言通用：绕开 ASR，直接用前端稿子；`language` 仅决定 sidecar 端的 MFA/参考表路由。
- 前端 i18n：`web/src/modules/i18n.js` 的 `SUPPORTED` 是所有 lang code 的唯一源，`analyzer.js` / `main.js` 里有显式 sync reminder 注释；DICT 四表（zh/en/fr/ko）必须键集相等，dev build 在 i18n.js 模块加载时跑 drift guard，失败抛错。

Sidecar 源码 vendor 自 [guojunximi-cell/gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization.git)（working-chinese-version，同步 2026-04-16 @ 446f124），放在 `voiceya/sidecars/visualizer-backend/`，FastAPI 薄壳在 `voiceya/sidecars/wrapper/main.py`。英文资源 `cmudict.txt` 从 upstream master 分支单独补入 vendor 目录（详见 `voiceya/sidecars/README.md`）。

## 本地数据资产（仅本机 D: 盘，不入仓库）

WSL 路径 `/mnt/d/project_vocieduck/`（Windows `D:\project_vocieduck\`）。**不进 git**——隐私（语音含说话人身份）+ 体积（CV fr 单项 ~32 GB）。所有 baseline 数值与 zone 阈值的源数据都在这里；新机器克隆仓库后跑 baseline 必须先复刻或外部存储。

### `calibration_v1/` — 555-session 校准数据

`tests/reports/calibration_v1/aggregate.csv` 与 `resonance_calibration.py` 现行 `_<LANG>_F_P*` 常量的源头。三语对称结构：

```
calibration_v1/
  {en-US, fr-FR, zh-CN}/
    raw/        # POST /analyze-voice 原始 .vga.json 导出
    sessions/   # 拆分 + 加 metadata 后的 session JSON（按 F/M 分桶）
    stitched/   # 60–90s 拼接的 WAV（送 sidecar 的实际输入；按 F/M 分桶）
  en-US/
    raw.5000hz_baseline_for_history/         # 2026-05-06 stats.json 重训前的 v0
    sessions.5000hz_baseline_for_history/    # 配套，对照「P75=0.987 sat 26%」用
```

文件计数（每语言）：raw / sessions ≈ 183–188，stitched ≈ 200。生成方式：`scripts/calibration_v1/build_corpus.py <lang>` + `aggregate.py`。**en-US 的 5000hz_baseline 子目录是历史档案**——不要改、不要删，再跑 ablation 时是唯一对照。

### `ablation/audio/` — 训练语料 + ablation 实验子集

```
ablation/audio/
  cn/
    AISHELL3/{train,test}/wav/<spk>/<utt>.wav   # 175 + 215 spk; train_stats_zh.py 的输入
    AISHELL3/{spk-info.txt, content.txt}        # transcript + speaker meta
    train_L/, train_S/                          # 含 TextGrid 的小集（~250 文件），对齐评估用
  en/
    LibriSpeech/train-clean-100/<spk>/...       # 251 spk; train_stats_en.py 的输入
    cmu_arctic_extracted/{cmu_bdl,clb,rms,slt}/ # 4 spk × 8 wav，curated fixture
    cis_female_en/, cis_male_en/                # 30 + 25 文件，curated 性别对照
  fr/
    clips/<hash>.mp3                            # CV fr v25 全 dump (~864k 文件，~32 GB);
    {clip_durations,validated,train,dev,test}.tsv   # CV 标注表
  normalized/                                   # 音量规范化后的小集
    {en_female,en_male,zh_female,zh_male}/      # 30/25/120/99 文件
```

哪个脚本读哪：

| 脚本 | 期望路径（默认或最常用 `--corpus`/`--aishell` 值） |
|------|-----------------------------------------------|
| `scripts/train_stats_zh.py` | `/mnt/d/project_vocieduck/ablation/audio/cn/AISHELL3` |
| `scripts/train_stats_en.py` | `/mnt/d/project_vocieduck/ablation/audio/en/LibriSpeech/train-clean-100` |
| `scripts/train_stats_fr.py` | CV fr 解压根（容器内 `/mnt/cv-fr/cv-corpus-25.0-XXXX/fr`） |
| `scripts/audit_resonance_*.py` | 同上，按语言对应 |
| `scripts/calibration_v1/build_corpus.py` | 写到 `calibration_v1/<lang>/{raw,sessions,stitched}` |

调试 baseline 漂移时：先看 `tests/reports/calibration_v1/aggregate.csv`（git 里有），再去 D: 盘对应 `sessions/<F|M>/*.vga.json` 找具体 session（每个 JSON 含完整 `summary.engine_c.phones[]`，能直接 diff per-vowel 数值）。

## 协作约束（自我框架）

1. **分支纪律**：当前分支 `dev-en`；合 main 需显式授权，不跨分支 cherry-pick。
2. **子模块/vendor 谨慎**：`voiceya/inaSpeechSegmenter`（k3-cat fork）和 `voiceya/sidecars/visualizer-backend/`（gender-voice-visualization zh 分支）都是以文件形式 vendor 进仓库的——不替换、不重置，只在明确要求时才动；upstream 升级走 `voiceya/sidecars/README.md` 里的 rsync 步骤。
3. **风格一致**：Python 遵 .ruff.toml（双引号、snake_case）；JS 遵 .prettierrc（tabs、camelCase、import sort）。编辑前先读周边文件匹配风格。
4. **接口边界**：FastAPI 路由只走 `routers/api.py`；SSE 事件结构在 `services/sse.py` 定义，改字段需前后端同步。Engine C 产出的 `summary.engine_c` 是可选字段，前端未消费前后端都可独立迭代。
5. **部署构型**：Dockerfile 已跑通 Railway；docker-compose.yml 是 VPS 通用路径（含 `engine-c` profile）。改 Docker 前先本地 `docker compose up --build` 验证。Engine C sidecar 镜像 ~2.5 GB，首次构建下载 MFA 模型耗时可达 10 分钟。
6. **禁区**：不动 .venv/、不 git add -A、不 --no-verify。
7. **高风险操作一律先确认**：删文件、改 CI、动提交历史、推远端、升/降依赖。
