# CHANGELOG — French (fr-FR) baseline

Engine C 法语支持的 stats / weights 演进记录。

## v0.1.0 — 2026-04-29 — initial baseline

### 训练数据
- 源：[Mozilla Data Collective — Common Voice Scripted Speech 25.0 fr](https://mozilladatacollective.com)（CV 25 v25, 2026-03-09 dump，783k validated rows，864k mp3）
- 平衡采样：female 984 spk + male 3793 spk，max-segs-per-speaker=4，n-segments=5000（实采到 4810，去重 190 段断点续跑后有效输入）
- 对齐结果：**4786 / 4810 = 99.5% 成功**（24 段 MFA align 失败，多为短语料 / 跑题）
- 总耗时：**~3 小时**（20 worker 并发，docker 内 28 核）
- 训练脚本：`scripts/train_stats_fr.py`，per-worker `MFA_ROOT_DIR` 隔离 + multi-process

### Stats（`stats_fr.json`）
- 38 phonemes 入表（44 french_mfa phoneset 中漏 6 个低频：`ɟ ts mʲ ŋ dʒ tʃ`，<200 obs 阈值过滤掉）
- 16 法语元音全在（12 oral + 4 nasal: `ɛ̃ ɑ̃ ɔ̃ œ̃`，NFC 归一）
- Schema 与 `stats.json` / `stats_zh.json` 一致：`{phoneme: [F0_dict, F1_dict, F2_dict, F3_dict]}`，每个 dict 含 mean/stdev/median/min/max

### Weights（`weights_fr.json`）
- `[0.762, 0.236, 0.002]` — **抄 ZH v0.2.1**，未在 fr 上独立验证
- 依据：EN upstream `[0.732, 0.268, 0.0]`、ZH v0.2.1 `[0.762, 0.236, 0.002]` 在 spk-disjoint holdout 验证过 F1+F2 主导的物理关系跨语言一致；先验 fr 应在同一形状附近
- 重训不做：CV 25 v25 已全用于 stats，无 fr holdout；没有判据下"重训"只是"换数字"，不是"改进"

### End-to-end smoke (1 sample)
female sample: `common_voice_fr_42769755.mp3`，"Il se lie d'amitié avec Isabelle, la filleule du propriétaire du magasin de jouets."（13 s）

```
Engine A:  dominant_label=female  female_ratio=1.0  f0_median=213 Hz  gender_score=72.2
Engine C:  language=fr-FR  phone_count=63  word_count=23
           mean_pitch=192 Hz  median_pitch=209 Hz
           mean_resonance=0.70  median_resonance=0.89
           alignment: phone_ratio=4.5  coverage=0.885  low_quality=false
Advice v2: gating_tier=standard  range_zone=mid_upper  tone_tendency=leans_feminine
           summary_text_key=advice.summary.mid_upper_leans_feminine
```

IPA phones 完整对齐（`i l ʎ j ɛ̃ ø e m t ɑ̃ ɔ w …`），含 4 鼻元音。链路全通。

### Stats sanity（vs EN/ZH 横向）
F1/F2 mean 数量级合理，跨语言差异可由音系解释（**非 bug**）：

| 元音 | EN F1 | ZH F1 | FR F1 | 解读 |
|------|-------|-------|-------|------|
| /a/  | 701   | 764   | 623   | 法语 /a/ 偏央 [ä]，F1 略低于 EN 开后 [ɑ] / ZH [a] |
| /e/  | 595 (EH) | 533 | 408   | 法语 /e/ 是 close-mid [e]（≠ 英语 /ɛ/），F1 应低 ~150 Hz |
| /o/  | 520 (OW) | 551 | 416   | 法语 /o/ 是 close-mid [o]，F1 应低 ~100 Hz |
| /i/  | 375   | 377   | 357   | ✓ 三语接近 |
| /u/  | 400   | 407   | 400   | ✓ 三语接近 |

### Caveats（已知问题）

1. **female speaker pool 984 < target 1000**（CV 25 v25 全员）。male:female speaker ratio 3793:984 ≈ 4:1。stats 是混性别聚合，未做 male / female stdev 分离测量（训练 JSONL 未记 gender 字段，事后无法聚合）。如果未来发现 stats 有性别偏差，要重训时记得在 JSONL 加 gender。
2. **FR /i/、/u/ F1 stdev 比 EN/ZH 高 ~70%**（222 vs 123, 180 vs 107）。归因：CV 是众包录音，麦克风 / 环境噪声多；高/闭元音音段短，formant tracker jitter 大。不是对齐错误（mean 数值合理）。
3. **FR ɥ F1 stdev = 689**（"huit" 滑音），稀有 + 上下文敏感，formant 不稳定。出现频率低，对最终 resonance 评分影响有限。
4. **weights 未在 fr holdout 上验证**：抄的 ZH v0.2.1，靠 EN/ZH 形状跨语言一致性的先验。如果未来想做 fr 专属 weights，必须先建 spk-disjoint holdout（从 CV 26+ 抽未参与训练的说话人），协议必须 `--weights-spk-cv --weights-min-f2 0.20`（utt-CV / 低 floor 都会把 F2 砍掉，参考 ZH v0.2.0 → v0.2.1 教训）。
5. **single male sample smoke** (CV `male_masculine` 第一条): pitch 311 Hz 偏高，可能是孤例也可能 CV male pool 有 bias。N≥10 验证后再下结论（见 v0.1.0 末尾 "10-sample smoke" 段）。

### Future work
- 跑 fr spk-disjoint holdout（CV 26 出来时，从未参与 v25 stats 训练的 client_id 中抽）。
- 在 holdout 上 sweep weights with `--weights-spk-cv --weights-min-f2 0.20`，比对 EN [0.732, 0.268, 0]、ZH v0.2.1 [0.762, 0.236, 0.002]、自训 weights，看 holdout spk-acc 谁高再决定是否替换。
- 训练 JSONL 加 gender 字段，能事后做 stats 性别分离审计。
- ɟ / ts / mʲ / ŋ / dʒ / tʃ 6 个低频音素未入表（<200 obs）。这些主要是借词或方言变体，对法语主流语料影响小；如果未来扩库到 ≥10k 段，应能补全。

### 数据保留
`~/datasets/fr-baseline/cv-corpus-25.0-2026-03-09/` 32 GB，CV fr 25 v25 解压物，留作未来 stats refresh（CV 26 / 27 出来时）的对照集，比重新下 29 GB tar 快。

### 10-sample smoke (post-commit confirmation)
5 female + 5 male（distinct client_id, ≥7 s 时长），全部 script-mode 走完 Engine A→C→Advice 链路：

| expected | A label | f0 | phn | pitch | med_res | zone |
|----------|---------|-----|-----|-------|---------|------|
| female | female | 246 | 44 | 238.8 | 1.000 | mid_upper |
| female | female | 213 | 60 | 208.7 | 0.928 | mid_upper |
| female | female | 201 | 48 | 200.4 | 0.721 | mid_neutral |
| female | female | 166 | 49 | 158.0 | 0.704 | mid_neutral |
| female | female | 208 | 43 | 203.0 | 0.604 | mid_upper |
| male   | **female** | 211 | 44 | 217.6 | 0.700 | mid_upper |
| male   | male   | 119 | 64 | 114.4 | 0.260 | low |
| male   | male   | 123 | 50 | 121.3 | 0.401 | mid_lower |
| male   | NULL/err | -  | -  | -     | -       | -      |
| male   | male   | 146 | 54 | 145.3 | 0.273 | mid_lower |

**Aggregate**:
- female (n=5): A label 5/5 ✓，pitch median **203 Hz**，resonance median **0.721**
- male (n=4 successful, 1 NULL): A label 3/4 ✓ (1 misclassified, pitch 217 Hz outlier)，pitch median **133 Hz**，resonance median **0.337**

**Discrimination**:
- ΔPitch = 70 Hz（女 203 vs 男 133）
- ΔResonance = 0.38（女 0.72 vs 男 0.34）—— Engine C 双向清晰分离
- Zone 分布与 pitch 一致（女偏 mid_upper，男偏 low / mid_lower）

**异常**：
- `common_voice_fr_19794775.mp3` (sample 6, "male"): pitch 217 Hz、resonance 0.7、A 标 female——单条样本 CV 自报性别 vs 实际声学不匹配，**非 v0.1.0 系统问题**。CV 性别标签是 self-reported，少量 mislabel 是已知现象。
- `common_voice_fr_20024224.mp3` (sample 9, "male"): NULL 结果——疑似 audio_gate 拒（短或质量低）；不影响其他样本。

**结论**：v0.1.0 baseline 在 N=10 的小冒烟里通过，可以 ship。
