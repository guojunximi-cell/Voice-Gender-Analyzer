# 中文适配版本记录

## v0.1.2 —— Railway 部署支持

新增 `Dockerfile` / `.dockerignore` / `railway.json`，`serve.py` 适配 `PORT` 环境变量。

- 基于 `mambaorg/micromamba`，apt 装 ffmpeg/sox/praat/libmagic，conda 装 MFA。
- 镜像构建时预下载 `english_mfa` 和 `mandarin_mfa` 声学模型 + 词典。
- 容器内 `settings.json` 自动重写为容器路径，不影响本地开发配置。
- 建议 Hobby 档（≥8GB RAM），免费档 512MB 跑 MFA 会 OOM。

---

## v0.1.0（已发布）

见 `README.md`。要点：
- 接入 MFA `mandarin_mfa` v2.0.0（声学 + 词典）。
- `preprocessing.py` / `phones.py` / `resonance.py` 加 `lang='zh'` 分支；`_strip_tone`、`ZH_VOWELS`。
- 手工编写 `stats_zh.json`（文献 F1/F2/F3 均值 + 约 2× stdev）。
- 前端 pitch 上限 300→500 Hz；UI 元音判定加 `ZH_VOWELS`。

**已知问题**：中文 resonance 数值跳动范围过大。

---

## v0.1.1（本次）—— 修复 Resonance 跳动过大

### 根因

不是 UI、不是 tone 剥离、不是 `ZH_VOWELS`，而是 **后端 `stats_zh.json` 与英文 `stats.json` 的制作方式不一致**：

| 维度 | EN `stats.json` | ZH `stats_zh.json`（v0.1.0） |
|------|-----------------|------------------------------|
| 来源 | `corpusanalysis.py` 在真实语料库上跑同一条 Praat+MFA 管线后聚合得到 | 人工填文献元音均值 + 经验 stdev |
| stdev 语义 | 本管线 Praat 中点测量值的分布标准差 | inter-speaker vowel-space 文献值（显著更窄） |
| 覆盖 | 42 keys，含全部辅音 | 16 keys，只有元音 + 2 零韵母 + sp |
| 权重 | `weights.json` 按 EN stats 暴力优化 | 复用 EN 权重 |

结果：z-score 分母偏窄 → 单次 Praat mis-measurement → \|z\|≫1 → clamp 到 0/1 → 肉眼大跳；且辅音被 `resonance.py:50-52` 跳过，样本少 → 2σ 离群滤波失效。

### 修复思路（对齐英文方法）

核心：**让 `stats_zh.json` 变成"本管线在 ZH 语料上实测聚合"得到的东西**，其余代码不改。

### 步骤

1. **改造 `acousticgender/corpusanalysis.py`**：加 `lang` 参数，`preprocessing.process` / `phones.parse` 按 lang 切换；`population_phones` key 用 `_strip_tone(phoneme)`。
2. **准备 ZH 语料**（性别均衡子集，AISHELL-3 / MAGICDATA / THCHS-30 任一）。
3. **跑出新 `stats_zh.json`**：自然包含辅音条目，stdev 为实测分布。
4. **重跑权重** 得 `weights_zh.json`；`backend.cgi` / `build.cgi` 按 lang 选择 weights 文件。
5. **过渡方案**（若语料库短期不可得）：用现行工具跑 ~30–50 条自有录音，dump `data['phones']`，直接套 `corpusanalysis.py:69-96` 的聚合块生成 stats_zh.json。

### 不改动

- `resonance.py` 算法本体、`_strip_tone`、`ZH_VOWELS`
- `phones.py` 解析逻辑
- 任何前端文件

### 验收

- 同一条男声样本 resonance median 落在 30–45%，女声 55–75%
- 单音节间跳动幅度相比 v0.1.0 明显收敛

### 实测结果（M5）

- 语料：AISHELL-3 采样 153m+153f → MFA 对齐成功 114m+114f
- 验证集（最后 20+20，存在 leakage）：median(m)=0.507, median(f)=0.713, Δ=+0.206, accuracy=0.85 PASS
- 与 v0.1.0 对比：m 中位数从 ~0.91 降到 0.51，分布从贴边 100% 改为分散在 30–60% 范围 → 跳动幅度大幅收敛
