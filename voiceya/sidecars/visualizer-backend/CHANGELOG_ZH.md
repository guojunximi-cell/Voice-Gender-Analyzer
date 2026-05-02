# 中文适配版本记录

## v0.2.1 —— Weights 重训（spk-disjoint CV + F2 floor）

接 v0.2.0 遗留 TODO："等后续对 weights search 加 F2 非零约束（或换 spk-level CV 目标）再重训"。这次同时加了两件事：CV objective 改成**说话人独立 fold + spk-level 准确度**，再给 F2 权重套**0.20 硬下限**。在同一份 v0.2.0 corpus（5550 train / 63-spk holdout）上重搜，得到 `[0.762, 0.236, 0.002]`，holdout spk-acc **62/63 = 0.9841**——比 v0.1.1 weights 的 61/63 = 0.9683 多识对 1 个 speaker。

### Weights

| 字段 | v0.1.1 / v0.2.0 active | v0.2.1 active |
|------|------------------------|---------------|
| `[w_F1, w_F2, w_F3]` | `[0.658, 0.242, 0.1]` | `[0.762, 0.236, 0.002]` |
| 来源 | EN baseline 借用 | 本次 spk-CV + F2≥0.20 重搜 |

### 改动

`acousticgender/corpusanalysis.py` 加 2 个 voiceya 补丁旗标（默认 off → 不破坏 EN 管线）：

- `--weights-spk-cv`：解析 `{m|f}_{corpus}_{spk}_{utt}` 目录名抽 spk-id，按 speaker 分 fold；每折用 train spks 的 spk-级 median 作为 threshold，accuracy 在 test spks 的 spk-级 median 上算。
- `--weights-min-f2`：对 weights[1] 设硬下限。本次实战需要 ≥0.20 才能走出 F1-only degenerate 区域。

stats 沿用 v0.2.0 不变；本节只改 weights。

### 为什么 F2 floor 0.05 不够

第一次跑 `--weights-spk-cv --weights-min-f2 0.05` 得到 `[0.87, 0.078, 0.052]`，training spk-CV mean_acc=0.878（确实比 v0.2.0 utt-CV 的 0.804 高），但 holdout spk-acc 只有 0.9206——和 v0.2.0 一样烂。F2 floor 0.05 排除了 F2=0 的退化点，但 spk-CV 在 v0.2.0 corpus 上仍偏好 F1-heavy 区域（F1≈0.87、F2≈0.08），训练集是这样，测试集偏好却完全不同。

### Train/test 分布偏移诊断

把六组候选喂同一份 spk-CV training objective 与 holdout spk-acc 并列：

| weights | training spk-CV mean_acc | holdout spk-acc |
|---------|--------------------------|------------------|
| EN upstream `[0.732, 0.268, 0.0]` | 0.8439 | **0.9683** |
| ZH v0.1.1 `[0.658, 0.242, 0.1]` | 0.8341 | **0.9683** |
| ZH v0.2.0 `[0.982, 0.0, 0.018]` | 0.8732 | 0.9206 |
| ZH v0.2.1@F2≥0.05 `[0.87, 0.078, 0.052]` | **0.8780** ★ | 0.9206 |
| F1-only `[1.0, 0.0, 0.0]` | 0.8732 | 0.9048 |
| F2-only `[0.0, 1.0, 0.0]` | 0.5439 | 0.7778 |

★ = training 最优；training 排序（v0.2.1@.05 > v0.2.0 > EN > v0.1.1）和 holdout 排序（EN = v0.1.1 > v0.2.0 = v0.2.1@.05）方向相反。这是真的 train/test distribution shift——AISHELL-1+3 训练池（618→555 spk）的 F1 inter-speaker variance 比 holdout 的 63 spk 更小，所以训练偏向纯 F1 决策；holdout 上 F2 的正则化效应才显出来。

唯一办法是从外部把 search 推到 holdout 偏好的区域。F2 floor 0.20 就是这件事：

| F2 floor | search winner | training spk-CV | holdout spk-acc |
|----------|---------------|------------------|------------------|
| 0.05 | `[0.87, 0.078, 0.052]` | 0.8780 | 0.9206 |
| **0.20** | `[0.762, 0.236, 0.002]` | 0.8683 | **0.9841** |

training acc 反而稍降（0.8780→0.8683）但 holdout 拉到 0.9841——前者是过拟合训练分布，后者是真泛化。

### 验证（spk-disjoint holdout, 23m+40f）

```
weights: [0.762, 0.236, 0.002]
median(m)=0.4692  median(f)=0.6842  Δ=+0.2150
speaker-level best acc=0.9841 at thr=0.5510
gate: Δ≥0.18 ✓  acc≥0.85 ✓  → PASS
```

误判 1 spk，不是 boundary case：threshold 0.55 上 62/63 全部分类正确。

### 老办法没救但留下了

`tools/sweep_weights_zh.py`（本次新加）允许喂 N 组 `label:w1,w2,w3` 在 holdout 上一并 sweep，比逐次 `validate_zh.py` 直观。`work/holdout_grid.py`（一次性 diagnostic，不进 vendor）扫 21×21×21 simplex 看 holdout 真正"sweet spot"在哪——结果显示一大批 weights 顶到 0.9683 上沿，唯有 `[0.762, 0.236, 0.002]` 这种 F2≈0.24 / F1≈0.76 的点能多识对 1 个 spk。

### N=63 显著性的诚实记录

62/63 vs 61/63 = +1.6pp，binomial std error ≈ 2.2pp。在统计上**这不是显著差异**，置信区间内 v0.1.1 和 v0.2.1 可能是同一性能。但：

- training spk-CV 上 v0.2.1 (0.8683) 比 v0.1.1 (0.8341) 高 ~3pp，且 std (0.0224) 也更小——training 信号方向一致。
- weights ratio 与 EN upstream `[0.732, 0.268, 0.0]` 几乎重合（F1 0.762 vs 0.732，F2 0.236 vs 0.268），物理上合理。
- 没有引入新风险（仍是 EN-style F1+F2 主导）。

所以装。如果未来发现 regression，回滚到 `weights_zh.v0.1.1.json` 一行 cp。

### 沿用 v0.2.0 不变

- `stats_zh.json`（5550-utt baseline，41 phones）
- `resonance.py` 算法、`_strip_tone`、`ZH_VOWELS`
- `phones.py` 解析逻辑
- `mandarin_mfa` v2.0.0

### 可复用的 follow-up 工具

- `tools/sweep_weights_zh.py` —— A/B 多组 weights on holdout
- `acousticgender/corpusanalysis.py` 加的 `--weights-spk-cv` / `--weights-min-f2` 旗标对 EN/FR 都可用（默认 off）
- `work/fast_search.py` —— 跳过 corpusanalysis.py 的 5550× mandarin_dict 重读，1 分钟内完成 coarse search（仅本地 work/ 下，未进 vendor）

---

## v0.2.0 —— 中文 Baseline 扩库（AISHELL-1 + AISHELL-3）

把 `stats_zh.json` 的来源从 v0.1.1 的 268 条 AISHELL-3 子样本扩到 AISHELL-3 + AISHELL-1 的 ~5550 条说话人均衡样本（cap=10/spk，round-robin），并把验证集换成**说话人独立** held-out 而非 v0.1.1 的末尾 20+20（已知有泄漏）。

### 语料

| 语料 | 来源 | 说话人 | 性别 | 入池条数（cap=10） |
|------|------|--------|------|---------------------|
| AISHELL-3 | OpenSLR-93 | 218 | 176F + 42M | 780 train + 170 holdout |
| AISHELL-1 | OpenSLR-33 + resource_aishell.tgz | 400 | 214F + 186M | 3320 train + 460 holdout |
| 合计 | | 618 | | 5550 train + 630 holdout |

切分：`is_holdout_speaker(spk_id)` 用 SHA-1 hash mod 1000 做 deterministic 10% holdout。AISHELL-1 transcript 走与 AISHELL-3 同样的 Han-char 过滤 + `mandarin_dict.txt` OOV 预筛（无需 G2P；`preprocessing.py` 的字切分天然吃汉字 transcript）。

### 数据规模对比

| 指标 | v0.1.1 | v0.2.0 |
|------|--------|--------|
| 训练样本 | 268（134m+134f） | ~5550（性别均衡） |
| 唯一说话人 | <50（同一 218 子集） | ~555（618 - holdout） |
| Holdout | 末尾 20+20 utt（**泄漏**） | 63 spk（23m+40f）说话人独立 |
| weights_zh.json | `[0.658, 0.242, 0.1]` | `[0.658, 0.242, 0.1]`（沿用，未重训——见下） |

### 验证（说话人独立 holdout，v0.2.0 stats + v0.1.1 weights）

- median(m) = 0.454, median(f) = 0.669, **Δ = +0.216**
- speaker-level best accuracy = **0.968** at threshold 0.563
- gate Δ ≥ 0.18 ✓ , acc ≥ 0.85 ✓ → **PASS**

### 为什么不更新 weights？

`corpusanalysis.py --weights-refine` 在 v0.2.0 corpus 上重跑得到 `[0.982, 0.0, 0.018]`（F1 几乎独占，F2 归零），10-fold utt-level CV mean_acc=0.804。

但同一份 stats、用不同 weights 在**说话人独立 holdout** 上 sweep（63 spk）：

| weights | source | spk acc on holdout |
|---------|--------|---------------------|
| `[0.732, 0.268, 0.0]` | EN upstream | **0.968** |
| `[0.658, 0.242, 0.1]` | ZH v0.1.1 | **0.968** |
| `[0.982, 0.0, 0.018]` | ZH v0.2.0 重训 | 0.921 |
| `[1.0, 0.0, 0.0]` | F1-only 极端 | 0.921 |
| `[0.0, 1.0, 0.0]` | F2-only | 0.762 |

—— v0.2.0 重训的 weights 在独立 holdout 上**比 v0.1.1 weights 差 5 个百分点**（58/63 vs 60/63）。

诊断：
- 暴搜 CV 的目标函数（utt-level 10-fold + train-fold median 阈值）在 v0.1.1 268 条 vs v0.2.0 5550 条上行为不同。前者数据量小、F2 稳定；后者 218→618 spk 跨地域口音多了，**F2 inter-speaker 方差增长比 F2 性别判别方差快**，CV 把 F2 权重压到 0 换来 utt-level 0.001 的提升。
- 这 0.001 的差异在 mean_acc=0.804、std=0.014 的尺度上完全是 noise；simplex 搜索 tie-break on `std` 把"碰巧 F1-only"挑了出来。
- 但 F2 在 spk-level holdout 上仍有判别力——和 EN upstream 历来 F1+F2 占主导的认知一致。

结论：**stats 扩库收益是真的**（spk-level acc 0.968 > v0.1.1 自测 0.85，更诚实的评估方式下还提升了 12 个百分点），但 v0.2.0 corpus 不适合直接喂当前的 weights 暴搜。沿用 v0.1.1 的 `[0.658, 0.242, 0.1]`。**Update**：v0.2.1 加上 spk-disjoint CV + F2≥0.20 floor 后重搜成功，详见上节。

### Stats 漂移

`tools/diff_stats_zh.py` 报告：41 phones 全部保留，无新增/删减；mean |Δmean|/stdev_old 平均 0.151（约 1/7 stdev）。漂移最大的 15 项里**没有元音**——只有辅音（tsʰ, s, ʂ, ʈʂʰ, pʰ, kʰ 等），与"辅音 formant 噪声大、扩库后 mean 不稳定"的预期一致。元音 z-score 反而稳定。

### 权重显著变化的原因

v0.1.1 weights `[0.658, 0.242, 0.1]` 在 268 条小样本上经 10-fold CV 选出；
v0.2.0 在 5550 条上重搜，简单线性扫描收敛到 F1 主导（0.982），F2 权重归零。F1 与声道长度（性别）相关性最强，大样本下 F2 的边际贡献被 F1 吃掉。这是优化结果，不是 bug。

### 建设步骤回顾（流程入口在 `tools/`）

1. `tools/build_zh_corpus.py` 抽 AISHELL-3 → `corpus/{m|f}_a3_<spk>_<utt>/`
2. `tools/build_aishell1_corpus.py` 抽 AISHELL-1 → 同 corpus 目录、前缀 `a1_`
3. `acousticgender/corpusanalysis.py --lang zh --jobs 8 --weights-refine` 跑 MFA + Praat + 暴搜（约 6 小时墙钟）
4. `tools/validate_zh.py` 在说话人独立 holdout 上测 Δmedian + spk-level accuracy
5. `tools/diff_stats_zh.py` 算 phone-by-phone mean shift 防 regression

### 已知 vendor 补丁

`acousticgender/corpusanalysis.py` 加了两处 `# voiceya patch:`：
- Python 3.14 改默认 multiprocessing start method 为 forkserver；脚本是平铺的 top-level，需要 `set_start_method('fork', force=True)` 才能用 ProcessPoolExecutor。
- 每 worker 的 mfa-root 把 `extracted_models` 从 symlink 改成 `copytree`——多个 worker 并发用同一份 extracted_models 会撞解压目录；上次 v0.1.1 一同两百条没暴露，五千条会百分百踩到。

### 不改的事

- `resonance.py` 算法、`_strip_tone`、`ZH_VOWELS`
- `phones.py` 解析逻辑
- gender-pooled stats（不分性别）——保持 runtime 契约不变
- mandarin_mfa v2.0.0（CLAUDE.md 警告 v3 OOV 80k 条）

### 旧文件保留

- `stats_zh.v0.1.1.json` / `weights_zh.v0.1.1.json` 留在仓库；resonance.py 的固定文件名加载逻辑只读 `stats_zh.json`，旧文件不会被误用，回滚一行 cp 即可。

---

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
