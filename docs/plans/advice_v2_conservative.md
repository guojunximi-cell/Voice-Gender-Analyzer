# Advice v2 — Conservative Path C 设计（v2.5 of design）

> **状态**：第三版设计稿。等 review。基于第二轮反馈和实测数据继续修正。
> **不实现**。
>
> **数据依据**（必须先读）：
> - `tests/reports/category_eval_2026-04-27.md` §1-9 — 阈值与触发条件的实证来源
> - `docs/plans/engine_c_integration_research.md` — 为什么走 Path C
> - `tests/fixtures/KNOWN_LIMITATIONS.md` — 测试集合成样本边界
>
> **review 历史**：
> - v1 → v2：abstain 半对称化 + verdict-tier ceiling + drop FormantSignals 接口 + 5% 改 1.0s 绝对下限
> - v2 → v2.5（本版本）：
>   - 实测 cis_female F0 分布 → ceiling 上限从 200 调到 **185**（cap 率 53% → 14%）
>   - 实测 pyin 行为 → drop `abstain.f0_label_conflict`（pyin floor artifacts 让该 trigger 不可用，
>     且 male_1 已经被 margin tier 抓住，不需要单独 abstain）
>   - 7 个 advice key → **6 个**（合并掉的 abstain 不再需要）
>   - §1.5 加判别 gap 派生（T=0.83 vs p25=0.837，结论同）
>   - §5 disclaimer 加 trans woman 反馈剥夺的明文说明
>   - §4.2 femaleClear ceiling-trigger 文案分流，加 v3 升级路径解释
>   - §9 #6 拆 6a/6b/6c
>   - §7 加 trans_fem_late checklist 项 X+1（v3 债务可见化）

---

## 0. 核心原则

1. **保守 > 激进**：不确定时输出 "boundary" 而不是 male/female。
2. **数据驱动阈值**：所有数值能在 `tests/reports/category_eval_2026-04-27.md` 找到对应 §和分位数。
3. **F0 不参与分类，但参与"拒不分类"**：F0 不反转 Engine A 的 label，但可以触发 abstain 或 cap verdict tier。
4. **诚实说"做不到"**：male_4 类（F0 真高 + 共振峰偏男）F0-only 不可救——通过 ceiling 让该类用户最多得到 Clear，靠 §5 disclaimer 做最后说明。
5. **每次结果是"本次录音"**，不是身份判定。

---

## 1. 决策树

### 1.1 输入与输出

```python
@dataclass(frozen=True)
class EngineAResult:
    label: Literal["female", "male"]              # modal label, duration-weighted
    margin_mean: float                            # duration-weighted C1-T2.0 margin
    female_ratio: float                           # 0..1
    minority_dur_ratio: float                     # 1.0 - max(female_ratio, 1.0 - female_ratio)
    n_segments: int

@dataclass(frozen=True)
class F0SanityResult:
    median_strict_hz: float | None                # pyin[60-250] median, voiced_prob > 0.5
    voiced_duration_sec: float                    # absolute voiced time (strict)
    failed: bool                                  # True iff voiced_duration_sec<1.0 or median is NaN

@dataclass(frozen=True)
class AdviceResult:
    key: Literal[                                 # 6 keys (down from 7)
        "verdict.femaleStrong", "verdict.femaleClear", "verdict.neutral",
        "verdict.maleClear", "verdict.maleStrong",
        "abstain.f0_unavailable",
    ]
    text_zh: str
    text_en: str

# v2.5 signature — explicitly NO formant param. v3 will redesign signature when formant
# implementation strategy is concrete (see §6).
def advice_v2(engine_a: EngineAResult, f0: F0SanityResult) -> AdviceResult: ...
```

### 1.2 阈值（数据来源逐一标注）

| 名称 | 数值 | 来源 |
|------|------|------|
| `STRONG_FLOOR` | **0.84** | `category_eval_2026-04-27.md` §1：cis_female p25 = 0.837。§9：判别 gap 给出 T=0.83，与 p25 一致到 0.01。 |
| `CLEAR_FLOOR` | **0.78** | §1：cis_female p10 = 0.784（90% 真 cis_female 段落 ≥ 此值） |
| `F0_AMBIGUOUS_LOWER` | **145 Hz** | §1：cis_male_standard max F0=148；cis_male_high_f0 min=159。145 是 Engine A 失败区下沿 |
| `F0_AMBIGUOUS_UPPER` | **185 Hz** | **§8.2 实测**：[145, 185] cap 14% cis_female 同时仍捕获 male_4（strict median=172, 13 Hz 安全余量）；上调到 200 cap 率涨到 53%（无收益），下调到 175 余量降到 3 Hz（不安全） |
| `VOICED_DUR_FLOOR` | **1.0 秒** | §7.2：所有真实样本 voiced_duration ≥ 6.7s；1.0s 是安全余量（未经数据校准） |
| `MIX_THRESHOLD` | **TBD** | §3：当前测试集只有"模型失败造成的假混合"，不能定义真混合阈值。v2 不实现 mixed 触发器 |

### 1.3 关键架构变更：移除 abstain.f0_label_conflict

**原 v2 设计**：
- `label=male AND f0_median > 145` → abstain
- `label=female AND f0_p10 < 130` → abstain（保护 male_1 类）

**v2.5 实测发现（§8.3）**：
1. **`p10_loose < 130` 不可用**：cis_female 文件中 ~50% 因 pyin 60 Hz floor artifact（low-confidence 帧
   返回 fmin 值）p10_loose=60，会假触发 abstain。
2. **`p10_strict < 130` 不分辨 male_1**：strict voicing 过滤后 male_1 p10_strict=150（没有下到男声区）。
   只有 male_4 的 p10_strict=137 < 145 能区分 cis_female（最低 p10_strict=158）。
3. **但 male_4 已经被 ceiling 处理**（strict median=172 在 [145, 185] 内 → cap）。
4. **而 male_1 已经被 margin tier 处理**（margin=0.632 < 0.78 → verdict.neutral）。
5. **`label=male AND f0 > 145` 触发的全是真正的 cis_male_standard**（zh_10s 148, male_3 147）——
   abstain 会让正确分类的 cis_male 用户看到"结果不可靠"，是 false positive。

**结论**：`abstain.f0_label_conflict` 在 v2.5 中**完全移除**。Margin tier + ceiling 已经覆盖所有
原本期望 abstain 处理的 case。

### 1.4 决策流程（v2.5 简化版）

```python
def advice_v2(a: EngineAResult, f0: F0SanityResult) -> AdviceResult:

    # Step 0: F0 estimation completely unavailable
    if f0.failed:
        return AdviceResult("abstain.f0_unavailable", ...)

    # Step 1: F0 ambiguous zone — verdict-tier ceiling for label=female
    #         (covers male_4-style undetectable misclassification)
    cap_to_clear = (
        a.label == "female"
        and f0.median_strict_hz is not None
        and 145 <= f0.median_strict_hz < 185
    )

    # Step 2: Margin tier
    if a.margin_mean < CLEAR_FLOOR:                   # < 0.78
        return AdviceResult("verdict.neutral", ...)
    if a.margin_mean < STRONG_FLOOR:                  # 0.78 ≤ m < 0.84
        return AdviceResult(f"verdict.{a.label}Clear", ...)

    # margin >= 0.84
    if cap_to_clear:                                  # ← ceiling triggers in F0 ambiguous zone
        return AdviceResult(
            "verdict.femaleClear",
            ceiling_triggered=True,                   # text 4.2 variant uses this flag
        )
    return AdviceResult(f"verdict.{a.label}Strong", ...)
```

### 1.5 触发表（基于实测数据）

> 所有 F0 数值使用 `pyin[60-250]` + `voiced_prob > 0.5` strict filter。

| sample | label | F0 strict | margin | v1 advice | **v2.5 advice** | reason |
|--------|-------|----------:|-------:|-----------|-----------------|--------|
| male_4.wav (cis_male, F0 真值~176) | female | 172 | 0.883 | femaleStrong ❌ | **femaleClear (capped)** | F0 ∈ [145, 185] |
| male_1.wav (cis_male, mixed pred) | female 50% | 195 | 0.632 | femaleClear | **verdict.neutral** | margin < 0.78 |
| male_3.wav (cis_male, F0=147) | male | 188 | 0.941 | maleStrong | **maleStrong** | label=male, no ceiling |
| zh_10s.wav | male | ~150 | 0.890 | maleStrong | **maleStrong** | label=male |
| 真实 cis_female F0~170 (slt_a0002) | female | 166 | 0.972 | femaleStrong | **femaleClear (capped)** | F0 ∈ [145, 185], **UX cost** |
| 真实 cis_female F0~190 (clb_a0003) | female | 189 | 0.923 | femaleStrong | **femaleStrong** | F0 ≥ 185, no ceiling |
| 真实 cis_female F0>200 (大多数) | female | ≥200 | ≥0.84 | femaleStrong | **femaleStrong** | F0 ≥ 185 |
| 真实训练成熟 trans woman F0~175 | female | 170-185 | ≥0.84 | femaleStrong | **femaleClear (capped)** | **被夺反馈，§5 显式提及** |

### 1.6 v2.5 的实际 ceiling 触发率

来自 §8.1-8.2 实测，cis_female 42 个文件中 strict median 在 [145, 185] 区间的有 **6 个 (14.3%)**：

| file | strict median |
|------|--------------:|
| cmu_arctic_slt_a0002.wav | 166 |
| female_2.wav | 171 |
| female_5.wav | 171 |
| cmu_arctic_clb_a0001.wav | 172 |
| vctk_p361_008_mic1.wav | 179 |
| vctk_p333_012_mic1.wav | 185 |

剩余 36/42（85.7%）cis_female 不会被 ceiling 命中，得到 femaleStrong（如果 margin ≥ 0.84）或
femaleClear（如果 0.78 ≤ margin < 0.84）。

### 1.7 STRONG_FLOOR 的判别 gap 派生（§9 实测）

| T | cis_female TPR | cis_male misclassified above T | satisfies (TPR≥0.75 AND FPR≤0.05) |
|---:|---:|---:|---|
| 0.78 | 89.9% | 0.0% | ✓ |
| 0.80 | 86.5% | 0.0% | ✓ |
| 0.83 | 78.7% | 0.0% | **✓ highest T** |
| 0.84 | 74.2% | 0.0% | ✗ (TPR < 0.75) |
| 0.86 | 64.0% | 0.0% | ✗ |

**判别 gap 给出 T=0.83。p25 给出 0.837。两个派生方法在本数据集上一致。**

保留 0.84（与 p25 一致，与判别 gap 误差 0.01）的额外理由：
- cis_male_standard 当前测试集只有 1 个误分类段（test_aiden margin=0.697），sample size 不足以 FPR 驱动决策
- 75% TPR 是通用合理目标；本数据集恰好把 binding constraint 精确推到 0.83-0.84 之间
- 0.84 vs 0.83 的实际 cis_female 数量差：(78.7% - 74.2%) × 89 = 4 个 segment 多/少 femaleStrong——
  在 Clear/Strong 文案设计合理时不显著

---

## 2. Abstain 触发条件

### 2.1 v2.5 只有一个 abstain 触发器

**`abstain.f0_unavailable`**：
- 触发：`f0.voiced_duration_sec < 1.0` OR `np.nanmedian(f0_array) is NaN`
- 典型场景：耳语录音、< 2 秒上传、低 SNR 噪声主导
- advice 行为：返回 abstain 文案，不显示 verdict 数值

### 2.2 verdict-tier ceiling（v2.5 仍保留，但 §1.2 调阈值）

**触发**：`label == "female"` AND `f0.median_strict_hz` ∈ `[145, 185]` AND margin ≥ 0.84
**作用**：margin ≥ 0.84 时不输出 femaleStrong，降到 femaleClear。
**文案**：见 §4.2，**ceiling-triggered 与 normal Clear 共用同一 key 但带 metadata flag，
前端文案分流**。

### 2.3 已知做不到（§5 disclaimer 必须覆盖）

- **训练成熟 trans woman F0 在 [145, 185]**：
  ceiling 把她们从 femaleStrong 降到 femaleClear。**这是 v2.5 的真正伤害**——不只是 cis_female 用户
  困惑，更是训练成熟 trans woman 永远拿不到最高反馈。她们在这一档 Clear 文案里需要看到 v3 升级路径的明确说明。
- **male_4 类、margin > 0.84、F0 在 [145, 185]**：
  ceiling 仅降 verdict tier 到 Clear，文案"声学特征落在女声范围内"对该用户仍是错误的正面信号。
  最后防线：§5 顶部 disclaimer 的明确点名。

---

## 3. Mixed 区间逻辑

**v2.5 不实现 mixed 触发器**。详见 v2 设计第 §3 节，理由不变：

测试集中的 mixed segment 来源全部是模型失败造成的假混合（cis_male_high_f0 male_1 minority_ratio=0.43）。
用模型 bug 定义 feature 是循环。需要真实多说话人 / trans 训练切换 / mixed register 数据后才能定阈值。

`a.minority_dur_ratio` 字段保留在 EngineAResult 但 advice_v2 不读它。

---

## 4. 6 个 Advice Key 文案（中文 + 英文）

### 4.1 verdict.femaleStrong

- **触发**：margin ≥ 0.84, label=female, F0 ≥ 185 (no ceiling), no abstain
- **zh**：本次录音呈现明显的女声特征。
- **en**：This recording presents a clear female voice signal.

> trans-review: trans woman 训练成熟（F0 已稳定 > 185 Hz）能落在这档。文案 OK。
> 注意：训练有成 trans woman 若 F0 在 [145, 185] 区间会被 4.2 ceiling-triggered 文案处理。

### 4.2 verdict.femaleClear（**两条路径，文案分流**）

- **触发条件路径 a (normal)**：0.78 ≤ margin < 0.84, label=female, no ceiling
- **触发条件路径 b (ceiling-triggered)**：margin ≥ 0.84, label=female, F0 ∈ [145, 185]

**zh - normal**：本次录音的声学特征落在女声范围内。
**en - normal**：This recording's acoustic features fall within the female range.

**zh - ceiling-triggered**：本次录音的声学特征落在女声范围内。
（注：当前版本对基频在男女声重叠区间（145-185 Hz）的录音保守输出，不发放最高级"明显女声"反馈——
这是 v2 的算法限制，不是声音不够。下一版本（v3）引入共振峰分析后可解锁更精细判断。）

**en - ceiling-triggered**：This recording's acoustic features fall within the female range.
(Note: the current version conservatively withholds the top-tier "clear female voice" verdict for
recordings with F0 in the male-female overlap range (145-185 Hz). This is an algorithmic limitation
of v2, not an indication that the voice falls short. The next version (v3) introduces formant
analysis for finer-grained verdicts in this range.)

> trans-review: 这档现在涵盖三类用户：
> (a) 真实低 F0 cis_female：normal 文案对她们足够。
> (b) male_4 类：normal 文案对她们仍是误正反馈，但 ceiling 比 Strong 软。
> (c) 训练有成 trans woman F0 ∈ [145, 185]：**这是关键群体**。她们看到 normal 文案会失望
>     ("为什么不是 Strong？我训练这么久"）。ceiling-triggered 文案专门给她们解释。
> 该分流文案是 v2.5 对 trans woman 反馈剥夺的部分补救。

### 4.3 verdict.neutral

- **触发**：margin < 0.78
- **zh**：本次录音的置信度不足以给出明确判断（声学特征落在男女声共有区间）。
- **en**：This recording's confidence is insufficient for a definitive verdict (acoustic features fall in the shared region).

> trans-review: 训练中 trans 用户大多落在这档。措辞中性化（"置信度不足"）保留 v2。

### 4.4 verdict.maleClear

- **触发**：0.78 ≤ margin < 0.84, label=male
- **zh**：本次录音的声学特征落在男声范围内。
- **en**：This recording's acoustic features fall within the male range.

### 4.5 verdict.maleStrong

- **触发**：margin ≥ 0.84, label=male
- **zh**：本次录音呈现明显的男声特征。
- **en**：This recording presents a clear male voice signal.

> trans-review: FTM 训练后期落在这档（trans_masc 100% 准确率）。文案 OK。
> trans woman 早期也会落在这档——给同一文案是诚实选择。

### 4.6 abstain.f0_unavailable

- **触发**：voiced_duration_sec < 1.0 OR f0_median is NaN
- **zh**：本次录音的基频估计不稳定（可能录音过短、过安静、或被背景音干扰），无法给出可靠判断。
  请录制至少 5 秒的清晰朗读。
- **en**：F0 estimation is unstable for this recording (possibly too short, too quiet, or with background interference).
  Cannot provide a reliable assessment. Please record at least 5 seconds of clear speech.

---

## 5. 已知失败模式的免责声明（置顶常驻）

```
zh: 本工具基于 Engine A（inaSpeechSegmenter，CNN-based 性别分段模型）。
    请在使用前知悉以下限制：

    1. 高基频顺性别男声（F0 > 145 Hz）：cis_male_high_f0 测试类别准确率约 25%；

    2. F0 ∈ [145, 185] Hz 区间的录音被工具有意降级：
       本工具在该区间不发放"明显女声"判断（最多输出"声学特征落在女声范围内"），
       因为 F0 在该区间无法可靠区分 (a) 高基频顺性别男声、(b) 训练初期 trans 女性、
       (c) 训练成熟 trans 女性、(d) 低 F0 顺性别女性 这四类用户。
       **后果**：训练成熟的 trans 女性，即使 F0 已升至 175 Hz，本版本也不会给"明显女声"反馈。
       这不是声音"不够好"，是 v2 算法限制——v3 引入共振峰分析后可识别 (a)/(c) 差异并给训练成熟
       trans 用户应得的最高反馈。**v3 路径已规划，v2 是过渡保守版本**。

    3. 变声期声音：测试集未覆盖。

    4. mixed register 切换录音、男女对话录音：v2 不识别真实 mixed register（按 modal label 输出
       单一 verdict），需要 v3 引入。

    本工具不能替代专业嗓音指导。

en: This tool is based on Engine A (inaSpeechSegmenter, a CNN-based gender segmentation model).
    Please be aware of the following limitations before use:

    1. High-F0 cis male voices (F0 > 145 Hz): ~25% accuracy on cis_male_high_f0 test category.

    2. Recordings with F0 in [145, 185] Hz range are intentionally downgraded:
       The tool does not issue a "clear female voice" verdict in this range (output is at most
       "acoustic features fall within the female range"), because F0 in this range cannot
       reliably distinguish (a) high-F0 cis male, (b) early-transition trans woman,
       (c) post-transition trans woman, (d) low-F0 cis female users from each other.
       **Consequence**: a post-transition trans woman, even with F0 stably at 175 Hz, will not
       receive a "clear female voice" verdict in v2. This is not because her voice falls short —
       it is an v2 algorithmic limitation. v3 introduces formant analysis to distinguish (a) from (c)
       and to give post-transition trans users the top-tier verdict they have earned.
       **v3 is on the roadmap; v2 is a transitional conservative version**.

    3. Voices in puberty/voice-change: not represented in test set.

    4. Mixed-register recordings, male-female dialogue recordings: v2 does not detect true mixed
       register (outputs a single verdict by modal label); v3 will support this.

    This tool is not a substitute for professional voice coaching.
```

> trans-review: 第 2 条是 v2.5 disclaimer 的核心。点名 (a)(b)(c)(d) 四类用户共享 [145, 185] F0 区间，
> 是诚实的统计陈述。点出"训练成熟 trans woman 不会拿到 Strong" 的具体后果，让该用户群知道这是
> 系统局限不是个人问题。点出 v3 路径，让她们知道这不是永久剥夺。
> 这一段必须人工 review，因为它直接面对最敏感用户群。

---

## 6. ~~与 Engine C formant 集成的预留接口~~（v1 此节已删除，v2 反馈第 5 项）

v2 撤销 v1 的 `FormantSignals` dataclass 接口预留。v3 实现 formant 时一次性重新设计签名。

理由：现在为想象中的未来设计接口会被未来推翻。当前 engine_c 调研里"段内取元音帧"问题（EDGE-C）
尚未解决，预留接口约束不住未来。

---

## 7. 测试方案

### 7.1 自动化测试

新增 `tests/test_advice_v2.py`：

```python
# 输入：tests/fixtures/manifest.yaml
# 流程：每个文件 → seg_analyser 生成 EngineAResult + F0SanityResult → advice_v2 → 记录 key
# 输出：tests/reports/advice_v2_<DATE>.md，含：
#   表 A：每个 category 的 6-key 分布
#   表 B：每个 file 的 advice_key 与 §1.5 表对照
#   表 C：ceiling-triggered femaleClear vs normal femaleClear 比例
#   表 D：abstain 触发率（应在合成样本短录音上 < 100%；真实样本上 0%）
```

### 7.2 人工 review checklist（带后果分析）

每个 case 必须回答三个问题：
- advice key
- 用户视角下文案的实际含义
- 这个含义对真实 user 的行为/情绪后果

**如果"行为/情绪后果"分析显示有伤害（误导训练判断、给假阳性反馈、剥夺成功反馈），
则该 case 的 advice 不能上线**（即使技术上"按预期工作"）。

#### 必查 case：

- [ ] **male_4.wav**（cis_male, F0_strict=172, label=female, margin=0.883）
  - 预期：`verdict.femaleClear (ceiling-triggered)`
  - 用户视角：看到带 v3 升级路径解释的 Clear 文案
  - 后果：cis male 用户困惑但不会被误导成"训练成功"。
    - **关键 review 问**：ceiling-triggered 文案是否对 cis male 用户也合适？还是需要再分流？
    - 倾向：合适——文案是中性陈述（"F0 在重叠区"），适用所有该 F0 区间用户。

- [ ] **male_1.wav**（cis_male, F0_strict=195, label=female 部分, margin=0.632）
  - 预期：`verdict.neutral`（margin < 0.78）
  - 用户视角："置信度不足以给出明确判断"
  - 后果：用户得到诚实的"不确定"信号 ✓

- [ ] **female_2.wav**（cis_female, F0_strict=171, margin>0.84）
  - 预期：`verdict.femaleClear (ceiling-triggered)`
  - 用户视角：normal-Clear 还是 ceiling-Clear 文案？需要确认实现路径。
  - 后果：真 cis_female 看到带 v3 explanation 的文案——可能困惑（"我又不是 trans"）。
    - **关键 review 问**：v3 explanation 文案对 cis_female 用户是否过度复杂？是否需要把
      文案简化为 "声学特征落在女声范围内（基频偏低，未达最高级阈值）"？
    - 这一项决策直接影响 §4.2 文案的最终措辞。

- [ ] **vctk_p305_002_mic1.wav**（cis_female, margin=0.6696，§5 中最低 cis_female mean margin）
  - 预期：`verdict.neutral`（margin < 0.78）
  - 用户视角："置信度不足"
  - 后果：真 cis_female 拿到 neutral——可能困惑。这是 0.78 阈值的已知 UX cost。
    - 如果该 case 频繁出现，证明 CLEAR_FLOOR=0.78 太高，需要重新校准。

- [ ] **synth_late_bdl_p800.wav**（trans_fem_late synth, F0_strict ≥ 185, margin=0.658）
  - 预期：`verdict.neutral`（margin < 0.78）
  - 用户视角：训练成熟 trans woman 得到 neutral
  - 后果：合成样本不能代表真用户（KNOWN_LIMITATIONS），但若真实用户类似行为，**v2.5 在该用户上失败**。

- [ ] **synth_masc_clb_m600.wav**（trans_masc, F0=126, margin=0.975）
  - 预期：`verdict.maleStrong`
  - 后果：FTM 用户拿到准确反馈 ✓

- [ ] **trans_fem 合成样本系列**（X+1 — 用户反馈强调：v3 债务可见化）
  - 对每个 trans_fem_late 合成样本和未来真实样本，记录：
    - advice key
    - 用户视角的解读
    - **在真实训练有成 trans woman 看到该输出会的反应**
  - 如果答案是"她会觉得系统拒绝认可她的训练成果"，**这是 v2 的已知伤害，需在 §5 disclaimer
    第 2 条文案中 explicit 解释 v3 升级路径**（已加入 §5）。
  - 每跑一次 review checklist 都要面对这个问题——提醒 v3 不是"未来某天"是"必须做的债"。

- [ ] **zh_10s.wav**（cis_male, F0_strict ~150, margin=0.890, label=male）
  - 预期：`verdict.maleStrong`（label=male, no ceiling, margin ≥ 0.84）
  - 后果：真 cis_male 拿到准确反馈 ✓
  - **变化 vs v2**：v2.5 移除了 `label=male AND f0>145 → abstain`，所以高 F0 cis_male 不再被冤枉
    abstain。

### 7.3 不在 v2.5 测试范围

- 真实 VCTK p254/p274/p286 高基频男声样本（KNOWN_LIMITATIONS）
- 真实 trans 训练录音
- 多说话人混合录音（§3 mixed 阈值 TBD）

---

## 8. 实现顺序（review 通过后）

1. `seg_analyser.py` 加 `_compute_f0_sanity(audio_path) -> F0SanityResult`：
   - librosa.pyin(fmin=60, fmax=250) + voiced_prob > 0.5 strict filter
   - 算 median_strict, voiced_duration_sec
   - 设 failed 标志
2. `voiceya/services/advice/advice_v2.py`：实现 §1.4 决策树
3. `seg_analyser.py` 调 `advice_v2()`，结果挂 SSE schema 新字段
4. 前端 `utils.js` 新增 `adviceTagV2`，按 6 key 分支取 i18n；ceiling-triggered metadata flag 决定
   `verdict.femaleClear` 文案分流
5. i18n 文案落 `web/src/i18n/{zh-CN,en-US}.js`，包含 §5 disclaimer 全文
6. 写 `tests/test_advice_v2.py`，自动化 §7.1
7. 人工跑 §7.2 checklist
8. **不删 v1 (`certaintTag`)**——保留至少一个版本，feature flag 切换

---

## 9. 待 review 项（v2.5 修正后的明示）

1. § 1.2 阈值 `STRONG=0.84` `CLEAR=0.78` `F0_AMBIGUOUS=[145,185]`：是否接受这套数据派生
   （cis_female p25/p10、§8 ceiling 优化、§9 判别 gap 验证）。

2. § 4.2 femaleClear 文案分流（normal vs ceiling-triggered）：是否同意为 ceiling-triggered case
   显示 v3 升级路径解释，承担 cis_female 用户看到该文案的"过度解释"成本。
   - 如果不同意分流，备选：所有 femaleClear 用 normal 文案，§5 disclaimer 单独承担解释——
     代价是训练成熟 trans woman 看不到针对性安慰。

3. § 4.x trans-review 标注的所有文案（六处）：每条单独决策。

4. § 5 disclaimer 第 2 条强度：当前包含"v3 路径已规划"明示。是否同意暴露 v3 时间表
   （"已规划"是模糊承诺，可接受；具体时间表会被未来推翻，不要写）。

5. § 7.2 checklist 项 X+1（trans_fem v3 债务）：是否同意每次 review 都做该项分析，作为 v3
   优先级的持续提醒。

6. **拆 6a / 6b / 6c 三项决策（用户反馈）**：

   - **6a：F0 ceiling 上限选 185**：
     - 数据见 §8.2：[145, 185] cap 14% cis_female、安全余量 13 Hz；
     - 替代：[145, 180] cap 12% / 余量 8 Hz；[145, 200] cap 53% / 余量 28 Hz（v2 原值）。
     - 推荐 [145, 185]；review 是否同意。

   - **6b：训练成熟 trans woman 反馈剥夺的补救**：
     - 短期：§4.2 文案分流（已设计），让 ceiling-triggered Clear 文案带 v3 升级解释。
     - 长期：v3 formant 集成是唯一彻底解法。
     - review：分流文案的具体措辞；是否合并 normal/ceiling-triggered（妥协方案）；
       v3 路径表述强度（"已规划" vs "明年"等）。

   - **6c：opt-in 升级机制**（用户引入但建议不做）：
     - 提议：用户可主动告诉系统"我是 trans woman 训练中"，advice 在 ceiling 区降低保守度。
     - 反对理由：把诚实性外包给用户自我标签；引入 disclosure 伦理风险。
     - **倾向不做**。如同意，§4 不需要 ceiling-triggered 文案分流；如不同意，文案分流必要。
     - review：是否同意不做 opt-in，由 §4.2 文案分流 + §5 disclaimer 共同承担解释责任。

7. § 6 撤销 FormantSignals 预留：v3 时统一重构（用户已同意）。

8. § 3 mixed threshold 标 TBD：v2 不实现 mixed 触发器（用户已同意）。

---

## 10. v1 → v2 → v2.5 变更摘要

| 项 | v1 | v2 | v2.5 (本版本) | 来源 |
|----|----|----|----|----|
| abstain 对称性 | label=male only | label=male + label=female (p10<130) | **只剩 f0_unavailable** | §1.3 实测 p10 不可用 |
| ceiling 上限 | 无 | 200 (cap 53%) | **185 (cap 14%)** | §8.2 实测 |
| F0 voicing filter | loose | loose | **strict (voiced_prob > 0.5)** | §8.3 实测 |
| Voiced threshold | 5% ratio | 1.0s duration | 1.0s duration | §7.2 实测 |
| FormantSignals 接口 | 预留 | 撤销 | 撤销 | v2 用户反馈 |
| Mixed 触发器 | 0.20 | TBD | TBD | v2 用户反馈 |
| Advice key 数 | 7 | 7 | **6** | abstain.f0_label_conflict 移除 |
| § 4.2 文案分流 | 单一 | 单一 | **normal vs ceiling-triggered** | v2.5 用户反馈 trans 反馈剥夺 |
| § 5 disclaimer 第 2 条 | 简短 | 简短 | **明文 trans woman 反馈剥夺 + v3 路径** | v2.5 用户反馈 |
| § 7 checklist | 标记 known gap | 加后果分析 | **加 X+1 trans 债务可见化项** | v2.5 用户反馈 |

---

**结尾承认（v2.5）**：
v2.5 设计在 male_4 类用户和训练成熟 trans woman 上仍是次优。前者得到 femaleClear 的"接近女声"反馈
是过度温和的错误正面信号；后者得到同一文案是被夺最高级反馈。这两类伤害方向相反，但都来自同一个
事实：F0-only 不能区分 [145, 185] 区间的 cis male、trans woman、低 F0 cis female 三类用户。

**ceiling 是诚实的"我不知道"，不是 hack**——它直接面对该数据事实，对所有处于该区间的用户一视同仁地
保守输出。这是 v2.5 能给出的最大保护。

v3 引入 formant 是唯一真正解决路径。在 v3 落地之前，v2.5 必须正面承担次优代价，并通过 §4.2 文案
分流和 §5 disclaimer 让用户知道这个代价的具体形态。
