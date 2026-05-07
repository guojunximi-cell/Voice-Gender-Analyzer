# CHANGELOG — English (en-US) baseline

Engine C 英文 stats / weights 演进记录。

## v0.2.0 — 2026-05-06 — re-train @ 5500 Hz Praat ceiling

### 触发因素

`tests/reports/calibration_v1/aggregate.csv` (2026-05-06 v0) 显示英文 cis-female
分布在 LibriSpeech train-clean-100（91 spk × ~60s 拼接）上严重饱和：

| | P5 | P25 | P50 | P75 | P95 | mean | sat 率 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| en F | 0.525 | 0.689 | 0.811 | **0.987** | 1.000 | 0.804 | **24/91 = 26 %** |
| zh F | 0.490 | 0.616 | 0.726 | 0.849 | 1.000 | 0.734 | 9/94 = 10 % |
| fr F | 0.430 | 0.547 | 0.646 | 0.752 | 0.960 | 0.659 | 3/90 = 3 % |

en F P75 紧贴 clamp 上限 0.98，导致 `resonance_calibration.py:_ZONES_EN` 的
`leans_female` 区间被压成零宽度（P75=0.98 → at_ceiling=0.98），75 % 的真实
cis-female speakers 被判定为 `mid_neutral`（"Androgynous range"）。

### 根因诊断

upstream `stats.json` 是 cmudict 派生、Praat 5000 Hz ceiling 烤出来的：

- `/IY1/` F2 mean = **2112 Hz**（Hillenbrand 1995 文献女声值 ~2960）
- `/IY1/` F2 stdev = **474 Hz**（异常宽，包含 LPC 失败的尾巴）

Praat 5-pole LPC 在 ceiling=5000 Hz 下，对真实 F2 ≈ 2900 Hz 的女声会**间歇性把
F1+F2 合并成 ~1300 Hz 的虚假峰**（`ceiling_selector.py:7-11` 注释解释了机制）。
upstream stats 是这种"成功 + 失败"测量的混合平均，所以参考分布的均值被人为压低。

清晰录音的 cis-female speakers 在测量真实 F2 时，对这个被压低的参考的 z-score
高达 +1.6 ~ +2.7，resonance score 直接顶到 clamp 1.0 → 26 % 饱和率。

### 修复方案

**完全照搬 zh 2026-05-01 的 stats_zh.json 重训路径**（参见 CHANGELOG_ZH.md
v0.2.0），区别仅在 corpus / phone inventory：

- 训练数据：LibriSpeech train-clean-100，125 F + 126 M speakers，FLAC 来源
- 训练脚本：`scripts/train_stats_en.py`（mirrors `scripts/train_stats_zh.py`，
  ~440 lines，~80% copy-paste；replaces AISHELL-3 parser with LibriSpeech
  SPEAKERS.TXT + per-chapter `.trans.txt`，replaces `mandarin_china_mfa` MFA
  model with `english_us_arpa`）
- 抽样：5000 segments，max_segments_per_speaker=25，speaker round-robin
- ceiling：固定 5500 Hz（同 zh），sidecar 端通过
  `wrapper/ceiling_selector.py:_ADAPTIVE_LANGS += {"en"}` 在运行时启用 4500–6500
  Hz 自适应选择，匹配新校准
- 对齐器：`PreloadedAligner.load("en", ...)` (kalpy)，sub-second per align after
  ~7 s warmup
- 总耗时：**605 s**（~10 分钟，8 worker 并发，docker 28 核 box）；
  4933 / 5000 = **98.66 % 对齐成功**，67 段失败（极短或 transcript drift）

### Stats（`stats.json`）

- 59 phones（vs 旧 42）— 多出来的 18 个主要是次重音 / 无重音元音变体
  （`AA0 AA2 AE0 AE2 AH2 AO2 AY2 EH0 EH2 IH2 IY2 OW2 UW2`）+ 5 个低频辅音
  （`JH Y ZH AW1 UH1`）
- `_MIN_OBS_PER_PHONEME = 200`，10 个 phones 因观测不足被丢弃（多为罕见辅音
  组合或 ARPABET 边缘标签）
- Schema 与 `stats_zh.json` / `stats_fr.json` 完全一致

### Stats sanity（vs 文献 + cross-language）

```
              OLD (5000 Hz baseline)        NEW (5500 Hz retrain)
              F1         F2         F3      F1         F2         F3
   /IY1/  375 ± 134  2112 ± 474  2708 ± 316    392 ± 275  2353 ± 336  2906 ± 305
   /IH1/  467 ±  99  1903 ± 356  2568 ± 307    474 ± 178  1928 ± 299  2768 ± 300
   /EH1/  595 ± 121  1631 ± 279  2403 ± 338    615 ± 147  1750 ± 256  2661 ± 320
   /AE1/  711 ± 171  1645 ± 319  2458 ± 350    675 ± 187  1794 ± 253  2693 ± 304
   /EY1/  482 ± 107  2026 ± 395  2665 ± 290    478 ± 151  2187 ± 302  2780 ± 266
```

`/IY1/` F2 平均上抬 **+241 Hz**（仍不到文献 2960，因 stats 是混性别聚合且
LibriSpeech 包含口音/年龄多样性 — 2353 是 LibriSpeech 整体 F2 mean，匹配实
际录音条件）。stdev 收紧（474 → 336）反映了 LPC 失败案例的减少。

### Weights（`weights.json`）

**未重训**，沿用 upstream `[0.7321, 0.2679, 0.0]`。理由同 fr：

- EN upstream `[0.7321, 0.2679, 0.0]`、ZH v0.2.1 `[0.762, 0.236, 0.002]`、
  FR v0.1.0（抄 ZH）已验证 F1+F2 主导是跨语言的物理常数
- 重训 stats 不改变"哪个 formant 重要"，只改变"参考分布在哪"；权重无需动
- LibriSpeech train-clean-100 251 spk 已全用于 stats，无 spk-disjoint
  holdout — 在没有 holdout 的情况下"重训"只是"换数字"

如果未来 calibration_v1 v2+ 上看到残留系统偏差，再补 holdout + sweep。

### Calibration_v1 v1 验证（end-to-end on 183 stitched LibriSpeech sessions）

```
              OLD (5000 Hz)               NEW (5500 Hz)
              P5    P25   P50   P75   P95  sat   P5    P25   P50   P75   P95  sat
   en F   0.525 0.689 0.811 0.987 1.000  26%   0.351 0.458 0.553 0.682 0.833   0%
   en M   0.328 0.381 0.489 0.639 1.000   8%   0.195 0.237 0.286 0.385 0.673   2%
```

- **饱和率：26 % → 0 %**（核心目标，达成）
- **F P75：0.987 → 0.682**（子-ceiling，`leans_female` 区间获得 ~30 % 实际
  宽度）
- F P50：0.811 → 0.553。看起来"分数下降"，实质是**参考分布被修正**导致 F
  speakers 不再异常偏高。0.5 = "z=0 vs F-population mean" 的设计语义首次被
  正确表达
- M-vs-F gap：+0.32 → +0.27（轻微收窄，仍清晰分离）
- 跨语言一致性：en F P50 = 0.55, zh F P50 = 0.73, fr F P50 = 0.65 — 三语
  现在都在同一量级（v0 时 en 离群最高至 0.81）

### Caveats（已知问题）

1. **F P50 = 0.553 视觉上比 v0 的 0.811 "低"**：UI 上"典型 cis-female
   speaker"现在显示 ~55 % 而非 ~80 %。这不是回退——v0 的 0.81 是 5000 Hz
   ceiling 把参考压低后的伪信号。新数字是诚实的 z-score 表达。如果 UX 觉得
   55 % 不够"令人鼓舞"，请在 advice 文案 / `_ZONES_EN` 文案层调整，**不要**
   再回退到 5000 Hz baseline。
2. **混性别训练**：125 F + 126 M 平衡训练，参考分布的 mean 在 M-F 中点附近。
   resonance.py 算法设计是 "0.5 = female reference mean"；混性别使
   "0.5" 实际偏 M 一些。同样问题 fr 也存在（CV fr 25 是 4:1 male skew），
   实测都能用。如果以后需要更纯的 F-anchor，可以补 `--gender female` filter
   再跑一次（~3000 segs from 125 F speakers）。
3. **/ER1/ F2 略下降**（1519 → 1455）：唯一一个不升反降的元音。归因 retroflex
   /ɚ/ 的 F3 主导 + LibriSpeech ER 标注的 dialectal variation；对 resonance
   评分影响可忽略（ER 在 weights 下贡献低）。
4. **18 个新增 phone variants 不影响分布形状**：filter-test 表明，把新 stats
   切回 41-phone 集合（=旧 stats 的去 sp 版本）后，F P50 = 0.552 vs full
   59-phone 的 0.553，差异在测量噪声内。所以分布偏移完全来自 41 个共有
   phones 的参考改变，不是新 phones 的稀释。

### 数据保留

- `voiceya/sidecars/visualizer-backend/stats.v0.upstream.json` — 旧 upstream
  baseline 留底，回滚一行 `cp` 即可。`resonance.py:52` 写死读 `stats.json`，
  所以旧文件在仓库里不会被误用。
- `/home/yaya/scratch/en_stats_train/en_phones.jsonl` — 训练 checkpoint，
  appendable + resumable。如果未来 corpus refresh（比如 LibriSpeech
  train-clean-360 加进来），用 `--aggregate-only` 模式就能重新生成新
  `stats.json`。

### Future work

- F-only stats（如果 v1 用了一段时间后 UX 反馈仍嫌混性别参考偏低）
- spk-disjoint holdout 上 sweep weights（CV en pretrain 出来后，从未参与
  v0.2.0 stats 的 LibriSpeech other-500 / dev-clean 子集抽 ~30 spk）
- `dev-clean` smoke 验证：拿 5 F + 5 M 没参与训练的 dev-clean speakers
  跑 `python run_app.py`，确认实测分布与 calibration_v1 v1 一致

### End-to-end smoke（验证用）

After committing this change, the operator should:

1. 重启 sidecar（`docker compose --profile engine-c restart visualizer-backend`）
   so `/app/stats.json` reloads from the rebuilt image — though
   `resonance.py:52` opens the file on each call, so the existing running
   container also picks it up via the live `docker cp` already done.
2. Open one known en cis-female recording in the browser. Confirm
   `Leans cis-female` text now reachable (was empty zone pre-retrain).
3. Re-run `python -m scripts.calibration_v1.build_corpus all --lang en-US`
   on a clean `raw/` and `sessions/` to regenerate the committed
   `aggregate.csv` + `README.md` with new numbers.
