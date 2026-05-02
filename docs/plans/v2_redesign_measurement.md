# v2 Redesign — Measurement + Tone Tendency (no verdicts)

> **Supersedes**: `docs/plans/advice_v2_conservative.md` (v2.5). v2.5 提议的 verdict + ceiling
> 路径在多轮 stress test 后被证实在两个核心 use case 上 silent fail, 本文档作为新方向取代它.
> v2.5 文档保留作为历史决策记录, 不删除.
>
> **Status**: 实施完成 (2026-04-27). 4 个决策点见 §10. 95-sample render 报告:
> `tests/reports/advice_v2_render_2026-04-27.md` (待人工 review).

---

## §0 重定位

### 为什么放弃 verdict

v2.5 计划把 ina (k3-cat fork CNN) 的二分类输出包装为 5 档 verdict
(`verdict.{femaleStrong, femaleClear, neutral, maleClear, maleStrong}`) + 1 档 abstain,
并叠加 `[145, 185] Hz` ceiling 修正. 在 95 样本测试集 (`tests/fixtures/manifest.yaml`) 和
`tests/stress_f0_window.py` 多轮 stress test 后, 此路径暴露两个根本性失败模式:

**Silent failure** (短录音 + 高基频男声)
- `male_4.wav` (true F0=176 Hz, real cis male) 完整文件 strict-voiced F0=172 Hz, 落入
  ceiling 区间, ceiling cap 把 verdict 从 femaleStrong 改成 femaleClear, 看似安全
- 但用户上传同一段音频的 8s 切片时, file-level F0 strict 在 < 15s 窗 0% computable,
  ceiling 触发依赖文件级 F0 聚合, 短窗下 ceiling 失效
- 结果: margin=0.94 + label=female + ceiling 不触发 → 输出 `verdict.femaleStrong`,
  对一个真实 cis male 输出 "强烈倾向女声", 用户无任何提示分类不可靠

**Systemic over-correction** (低基频真女声)
- 真实 cis_female 群体中 F0 ∈ [145, 185] 的说话人 (本数据集 6/42 = 14.3%) 在 ≥ 30s
  录音上 100% 被 cap 到 `verdict.femaleClear`, 永远拿不到 Strong
- 这不是阈值能调的成本: ceiling 的语义就是 "F0 在不可靠区间一律降档", 真女声只要 F0
  落在那个区间, 就被牵连
- 详见 `tests/reports/category_eval_2026-04-27.md` §8

### 根因

ina 的二分类被反复证实**几乎完全由 F0 驱动**. 它无法区分:
- "F0 升 + 共振也升" (cis 女声 / HRT 后 trans woman) — 应该判为 female
- "F0 升 + 共振没跟" (高基频 cis 男声 / 训练前 trans woman) — 应该判为 male

任何把这种 F0-only 信号包装成 verdict 的设计都会在边界群体 (上述两类) silent fail. 这是
模型本身的限制, 不是阈值能调好的.

### 新方向

放弃 verdict 输出, 改为三件事并列:
1. **多维度 acoustic measurement** — F0 数值 + 区间标注, 让用户看到原始事实
2. **粗略 tonal tendency** — ina 的 3 档归类, 不带数字, 不假装精确
3. **显式 caveat** — 永久声明 ina 在 165-200 Hz 区间不可靠, 不可被前端隐藏

让用户基于多个独立信号自己解读, 而不是把一个不可靠的二分类伪装成"答案".

---

## §1 输出 schema

新结构以 `summary.advice` 形式追加, 不动现有顶层字段 (`overall_f0_median_hz`,
`female_ratio`, `dominant_label`, `overall_confidence`, `analysis[]`). 现有字段保留作为
原始数据通道, `advice` 是新的呈现层.

```jsonc
"summary": {
  // 现有字段保留, 见 voiceya/services/audio_analyser/statics.py:18-87
  "total_female_time_sec": float,
  "total_male_time_sec": float,
  "female_ratio": float,                // 重定义语义, 见 §4
  "overall_f0_median_hz": int,
  "overall_gender_score": float,
  "overall_confidence": float,
  "dominant_label": "female" | "male" | null,
  "engine_c": {...} | null,

  // ── 新增 ────────────────────────────────────────
  "advice": {
    "schema_version": "v2",
    "gating_tier": "minimal" | "standard" | "full",
    "recording_duration_sec": float,

    "f0_panel": {                       // 始终输出 (即使 minimal tier)
      "median_hz": float | null,        // pyin[60-250] strict, voiced_prob > 0.5; null if unreliable
      "p25_hz": float | null,
      "p75_hz": float | null,
      "voiced_duration_sec": float,
      "range_zone_key": "low" | "mid_lower" | "mid_neutral" | "mid_upper" | "high" | null,
      "reliability": "ok" | "short_recording" | "insufficient_voiced"
    },

    "tone_panel": {                     // standard / full only; null in minimal
      "ina_label_distribution": {
        "female_frame_ratio": float,
        "male_frame_ratio": float,
        "other_frame_ratio": float
      },
      "tone_tendency_key": "leans_feminine" | "leans_masculine" | "not_clearly_leaning",
      "caveat_key": "ina.f0_bias_caveat"   // 永久 i18n key, 永远渲染
    } | null,

    "summary_panel": {                  // standard / full; null in minimal
      "text_key": "advice.summary.<zone>_<tendency>",
      "text_params": { "f0": int }
    } | null,

    "warnings": [                       // gating 触发的 warning 条带
      { "key": "advice.warning.<variant>", "params": { "duration": int } }
    ]
  }
}
```

### v2.5 已废弃元素 (本设计**不实施**, reviewer 一眼可对照)

| v2.5 元素 | 处理 | 替代 |
|----------|------|------|
| `verdict.femaleStrong` / `verdict.femaleClear` / `verdict.neutral` / `verdict.maleClear` / `verdict.maleStrong` | 全部不实现 | `tone_tendency_key` 3 档 (无 Strong/Clear 区分) |
| `abstain.f0_unavailable` 作为 advice key | 删除 | `f0_panel.reliability = "insufficient_voiced"` + 上层 gating |
| `[145, 185]` ceiling cap 逻辑 | 删除 | 用 caveat 把 F0 模糊区间问题暴露给用户, 不偷偷降档 |
| `STRONG_FLOOR=0.84` / `CLEAR_FLOOR=0.78` 双阈值 | 重定义为单阈值 | 0.78 划分 leans_* vs not_clearly_leaning |
| `AdviceResult.key` 6 元 enum | 删除 | 不存在单一"裁决" key |

---

## §2 ina 偏置 caveat (后端字段保留, UI 不渲染)

后端仍在 `tone_panel.caveat_key = "ina.f0_bias_caveat"` 输出该字段, 用于:
- 外部 API / SDK 消费者的 schema 完整性
- 未来 v3 共振峰接入后可能在 guided context 重启的可能性

**当前 UI 不渲染 caveat 段** (2026-04-27 user 决定): summary_panel 的单句文案
("F0 中位数 145 Hz, 位于中低基频区间. 倾向不明显.") 已经把 zone + tendency 平铺
为事实并列, caveat 段在标准/明确 case 上构成视觉冗余, 在 mid_neutral case 上的
警示作用由 zone tag (e.g. "声学中性区间") 在 PITCH 卡片里高亮承担.

i18n key `ina.f0_bias_caveat` 已从 `web/src/modules/i18n.js` 删除. 若 v3 决定恢复
显示, 重新加 i18n key + 在 metrics-panel.js renderAdvicePanel 内拉取 `caveat_key`
字符串即可, 后端无需改动.

---

## §3 录音长度 gating

依据 `tests/stress_f0_window.py` 的 voiced_dur 分布 (pyin[60-250] strict + voiced_prob > 0.5).
注意: 该 stress test 当时使用的 `voiced_prob > 0.5` 后续在 95-sample render 中证伪 (倍频锁定),
正式实现已切换到 `voiced_flag`. 但本节录音长度阈值 (10s/30s) 仍然合理: voiced_flag 下
voiced_dur 普遍更高, 对应阈值仍能截住"短录音 voiced 数据不足以稳定测 F0"的 case.

| Tier | 触发条件 (`recording_duration_sec`) | 显示 | 不显示 |
|------|-----------------------------------|------|-------|
| `minimal` | `< 10` | `f0_panel` (含 `reliability` 字段) + 现有 per-segment ina raw label timeline | `tone_panel`, `summary_panel` |
| `standard` | `[10, 30)` | `f0_panel` + `tone_panel` (含 caveat) + `summary_panel` + warning 条带 | — |
| `full` | `≥ 30` | 完整面板, 无 warning 条带 | — |

### Warning 文案 (新 i18n keys)

```
"advice.warning.short_recording_minimal":
  zh-CN: "录音少于 10 秒, 仅显示原始测量值. tonal 倾向需 10 秒以上录音."
  en-US: "Recording is under 10 seconds; only raw measurements are shown. Tonal tendency requires 10 s+."

"advice.warning.short_recording_standard":
  zh-CN: "录音较短 ({duration} 秒), 结果稳定性有限. 建议录制 30 秒以上以获得稳定结果."
  en-US: "Recording is short ({duration} s); result stability is limited. 30 s+ recommended for stable output."
```

### 阈值依据

来自 `tests/stress_f0_window.py` 输出:

| 说话人类型 | < 10s 窗 F0 computable | 10-15s 窗 | ≥ 30s 窗 |
|----------|----------------------|-----------|----------|
| 低基频 (~175 Hz, e.g. male_4 / female_2) | 0% | 0-24% | 100% |
| 中基频 (~200 Hz, e.g. female_1) | < 6% | 95% | 100% |

`< 10s` 下连 mid-F0 voices 都几乎不可计算 → minimal tier 不显示 tone (tone 必须有
F0 才能解读). `[10, 30)` 下 mid-F0 可靠但 low-F0 仍可能波动 → standard tier 显示 tone
但加 warning. `≥ 30s` 下全档 100% 稳定 → full tier 无 warning.

边界值 10/30 取整数, 非数据精确切割 (12/25 等), 优先用户记忆友好.

---

## §4 与现状的关系 (keep / delete / redefine)

| 组件 | 来源 | 状态 | 说明 |
|------|------|------|------|
| Engine A T=2.0 (`Gender.temperature`) | `voiceya/inaSpeechSegmenter/inaSpeechSegmenter/segmenter.py:266` | **保留** | C1 margin 校准基础, 不动 |
| C1 margin (`top1 - top2`) | `segmenter.py:223` | **保留** | tone_tendency 阈值唯一输入 |
| `pyin[60-250]` + `voiced_flag` (viterbi-smoothed) | 未实现 (v2.5 plan 提议) | **新增** | `f0_panel` 数据来源, 与现有 `acoustic_analyzer.py:50` 的 `pyin[65-1047]` 并存 (后者用于 segment 级 acoustics). v2.5 提议的 `voiced_prob > 0.5` strict gate 经实测在低 F0 男声上倍频锁定, 改为 `voiced_flag` 作为 voicing 判定 — 详见 `f0_panel.py` 顶部注释. |
| `voiced_dur ≥ 1s` strict floor | 未实现 (v2.5 plan 提议) | **新增** | `f0_panel.reliability` 判定 |
| `verdict.*` 5 档 advice key | v2.5 plan, 未实施 | **删除 (不实施)** | `tone_tendency_key` 3 档替代 |
| `[145, 185]` ceiling cap | v2.5 plan, 未实施 | **删除 (不实施)** | 用 caveat 暴露问题, 不再做 verdict 修正 |
| `abstain.f0_unavailable` advice key | v2.5 plan, 未实施 | **删除** | 替换为 `f0_panel.reliability` + gating |
| `STRONG_FLOOR=0.84` / `CLEAR_FLOOR=0.78` 双阈值 | v2.5 plan | **重定义为单阈值** | 0.78 划分 leans_* vs not_clearly_leaning |
| `summary.female_ratio` (后端) | `statics.py` | **保留 + 重定义语义** | 仍输出, 语义改为 "frame-level 标签分布", 仅展示百分比, 不参与决策 |
| `dominant_label` | `statics.py` | **保留** | tone_tendency 派生输入 (label + margin → tendency) |
| `certaintTag()` | `web/src/modules/utils.js:98-112` | **重定义** | 从 5 档文案 ("偏女性化" 等) 改为 3 档 tone_tendency_key mapper, 文案由 i18n key 驱动 |
| Gender spectrum bar (UI) | `web/src/modules/metrics-panel.js:191-195` | **保留 + 重命名语义** | 从 "gender confidence slider" 改写为 "ina 帧标签分布", UI 几何不变 |

### 兼容性

- 后端: `summary` 顶层字段全部保留, 老前端 / 老 SDK / 老报表脚本继续工作
- 前端: 加新代码读取 `summary.advice`; 老 result handler 在 advice 不存在时退化到原行为
- API 版本号: `summary.advice.schema_version = "v2"`. 未来若新增不兼容字段, 升至 "v3"

---

## §5 tone_tendency 三档划分

基于 ina margin (T=2.0 校准后) 与 dominant_label, **tone 旁不显示任何数字**:

| margin | dominant_label | tone_tendency_key |
|-------|----------------|-------------------|
| `≥ 0.78` | `"female"` | `leans_feminine` |
| `≥ 0.78` | `"male"`   | `leans_masculine` |
| `< 0.78` | any        | `not_clearly_leaning` |
| any    | null (no voiced segments) | (tone_panel 整体为 null, 由 gating 处理) |

### 阈值依据

`tests/reports/category_eval_2026-04-27.md` §1: cis_female margin p10 = 0.784, 即 90%
确认 cis female 样本 margin 高于此值. 单阈值取代 v2.5 双阈值 (0.78 / 0.84), 因为:
- "Strong" 档需要 confidence 概念, 与本设计 "tone 不带数字" 矛盾
- 双阈值在边界群体 (high-F0 cis male, low-F0 cis female) 上无法区分对错, 增加档位
  只是把同一个 silent failure 切成更细的 silent variants

### i18n keys (新增)

```
"advice.tone.leans_feminine":
  zh-CN: "倾向偏女"
  en-US: "Leans feminine"

"advice.tone.leans_masculine":
  zh-CN: "倾向偏男"
  en-US: "Leans masculine"

"advice.tone.not_clearly_leaning":
  zh-CN: "倾向不明显"
  en-US: "Not clearly leaning"
```

### 强约束 (实施 review 必查)

`tone_tendency_key` 文本旁边任何位置都不允许渲染数字:
- ❌ 不允许相邻 `margin` / `confidence` / `%` 数字
- ❌ 不允许 progress bar / slider 视觉化 tone tendency 强度
- ✅ 数字数据归属 `tone_panel.ina_label_distribution` (那是 "分布", 不是 "倾向")

如果 reviewer 在 PR 中提出 "倾向后面加个百分比吧", 应当回应: 那个值已经在
`ina_label_distribution.female_frame_ratio` 里以"分布百分比"语义展示, tone_tendency
是离散粗分类, 数字不属于这里.

---

## §6 F0 range_zone 划分 (去性别化)

5 档纯描述, 不绑定性别:

| range_zone_key | F0 区间 (Hz) | i18n key | zh-CN | en-US |
|----------------|--------------|----------|-------|-------|
| `low`          | `< 130`      | `advice.zone.low`        | 低基频          | Low |
| `mid_lower`    | `[130, 165)` | `advice.zone.mid_lower`  | 中低基频        | Mid-low |
| `mid_neutral`  | `[165, 200)` | `advice.zone.mid_neutral`| 声学中性区间    | Acoustically neutral |
| `mid_upper`    | `[200, 240)` | `advice.zone.mid_upper`  | 中高基频        | Mid-high |
| `high`         | `≥ 240`      | `advice.zone.high`       | 高基频          | High |

### 边界依据

来自 `tests/reports/category_eval_2026-04-27.md` §4 cis 群体 F0 分布:
- cis_male_standard F0 max = 148 Hz → `mid_lower` 上界与 `mid_neutral` 下界设在 165 Hz,
  确保所有标准男声落在 `mid_lower` 或更低
- cis_male_high_f0 F0 min = 159 Hz, 多数 ∈ [160, 195] → 落在 `mid_neutral`, 与 caveat
  锚定一致
- cis_female F0 strict p10 ≈ 165 Hz → `mid_neutral` 下界与 caveat 文案 "165-200 Hz"
  完全对齐
- cis_female F0 上限 ~245 Hz → `mid_upper` 上界 240 把绝大多数标准女声划到 `mid_upper`,
  仅极高基频 (儿童 / 部分头声) 进入 `high`

### `mid_neutral` 是 ina 不可靠区间

`mid_neutral` 区间 [165, 200) 与 caveat 文案中的 "165-200 Hz 区间无法可靠区分" 完全锚定.
该区间内的 F0 用户应**双重信号化**:
- 看到 `range_zone = mid_neutral`
- 同时看到 caveat 文案

视觉上, mid_neutral 标签本身可以加一个不打眼的 hint icon (鼠标悬浮显示 "ina 在此区间分类
不可靠"), 但实施时不强制 — caveat 已经覆盖.

---

## §7 summary_panel 文案 (< 50 字, 中英双语)

模板化 i18n keys, 由 `(zone, tendency)` 组合派生. 共 5 zones × 3 tendencies = **15 个 key**,
全部列出避免实施时遗漏:

```
"advice.summary.low_leans_feminine":
  zh-CN: "F0 中位数 {f0} Hz, 位于低基频区间. 声学倾向偏女."
  en-US: "F0 median {f0} Hz, low range. Leans feminine."

"advice.summary.low_leans_masculine":
  zh-CN: "F0 中位数 {f0} Hz, 位于低基频区间. 声学倾向偏男."
  en-US: "F0 median {f0} Hz, low range. Leans masculine."

"advice.summary.low_not_clearly_leaning":
  zh-CN: "F0 中位数 {f0} Hz, 位于低基频区间. 倾向不明显."
  en-US: "F0 median {f0} Hz, low range. Not clearly leaning."

"advice.summary.mid_lower_leans_feminine":
  zh-CN: "F0 中位数 {f0} Hz, 位于中低基频区间. 声学倾向偏女."
  en-US: "F0 median {f0} Hz, mid-low range. Leans feminine."

"advice.summary.mid_lower_leans_masculine":
  zh-CN: "F0 中位数 {f0} Hz, 位于中低基频区间. 声学倾向偏男."
  en-US: "F0 median {f0} Hz, mid-low range. Leans masculine."

"advice.summary.mid_lower_not_clearly_leaning":
  zh-CN: "F0 中位数 {f0} Hz, 位于中低基频区间. 倾向不明显."
  en-US: "F0 median {f0} Hz, mid-low range. Not clearly leaning."

"advice.summary.mid_neutral_leans_feminine":
  zh-CN: "F0 中位数 {f0} Hz, 处于声学中性区间. 声学倾向偏女."
  en-US: "F0 median {f0} Hz, acoustically neutral range. Leans feminine."

"advice.summary.mid_neutral_leans_masculine":
  zh-CN: "F0 中位数 {f0} Hz, 处于声学中性区间. 声学倾向偏男."
  en-US: "F0 median {f0} Hz, acoustically neutral range. Leans masculine."

"advice.summary.mid_neutral_not_clearly_leaning":
  zh-CN: "F0 中位数 {f0} Hz, 处于声学中性区间. 倾向不明显."
  en-US: "F0 median {f0} Hz, acoustically neutral range. Not clearly leaning."

"advice.summary.mid_upper_leans_feminine":
  zh-CN: "F0 中位数 {f0} Hz, 位于中高基频区间. 声学倾向偏女."
  en-US: "F0 median {f0} Hz, mid-high range. Leans feminine."

"advice.summary.mid_upper_leans_masculine":
  zh-CN: "F0 中位数 {f0} Hz, 位于中高基频区间. 声学倾向偏男."
  en-US: "F0 median {f0} Hz, mid-high range. Leans masculine."

"advice.summary.mid_upper_not_clearly_leaning":
  zh-CN: "F0 中位数 {f0} Hz, 位于中高基频区间. 倾向不明显."
  en-US: "F0 median {f0} Hz, mid-high range. Not clearly leaning."

"advice.summary.high_leans_feminine":
  zh-CN: "F0 中位数 {f0} Hz, 位于高基频区间. 声学倾向偏女."
  en-US: "F0 median {f0} Hz, high range. Leans feminine."

"advice.summary.high_leans_masculine":
  zh-CN: "F0 中位数 {f0} Hz, 位于高基频区间. 声学倾向偏男."
  en-US: "F0 median {f0} Hz, high range. Leans masculine."

"advice.summary.high_not_clearly_leaning":
  zh-CN: "F0 中位数 {f0} Hz, 位于高基频区间. 倾向不明显."
  en-US: "F0 median {f0} Hz, high range. Not clearly leaning."
```

### 文案约束

- **不用** "正确" / "错误" / "成功" / "失败" / "应该是" / "标准的" 等评价性语言
- **不用** "你是男声" / "你是女声" / "你的性别" 等身份判断语言
- **仅描述** 三条独立事实并列: (a) F0 数值, (b) F0 所处区间, (c) ina 给出的 tone 倾向
- **不联结** 三条事实做推论 ("F0 175 Hz 所以你是 X" 这种语义不允许出现)

### 字数

每条 zh-CN 文案约 22-28 字, en-US 约 7-10 词, 全部 < 50 字 (zh) / < 80 chars (en).

---

## §8 v3 formant 集成接口 (仅设计, 不实施)

v3 阶段在 Engine C 共振峰估计稳定后接入. 设计接口预留位置, 实施时再填:

```jsonc
"advice": {
  "f0_panel": {...},

  // ── v3 新增, 与 f0_panel 平级 ──
  "formant_panel": {
    "f1_median_hz": float | null,
    "f2_median_hz": float | null,
    "f3_median_hz": float | null,
    "vtl_estimate_cm": float | null,
    "reliability": "ok" | "insufficient_voiced",
    "decoupling_indicator_key":
      "f0_resonance_aligned"   // F0 与共振峰一致 (cis female / HRT 后)
      | "f0_above_resonance"   // F0 高但共振低 (高基频 cis male)
      | "f0_below_resonance"   // F0 低但共振高 (HRT 早期 trans woman, 训练中)
      | "ambiguous"            // 数据不足以判定
  },

  "tone_panel": {...},
  "summary_panel": {...}
}
```

### 视觉关系

- `f0_panel` 与 `formant_panel` **横向并列**, 同等权重 (不分主次)
- `decoupling_indicator` 用单独条带显示在 formant_panel 内, **不混入 tone_tendency**
  (tone_tendency 仍然只是 ina 二分类的粗略归类)
- `summary_panel` 文案在 v3 升级时会增加 formant 维度的描述, 但仍然遵守 "事实并列, 不
  做推论" 的约束

### v3 与 tone_tendency 解耦

关键设计选择: `decoupling_indicator` 不修改 `tone_tendency_key`. 即使 formant 显示
F0_above_resonance (高基频男声特征), tone_tendency 仍按 ina margin 判 leans_feminine
(因为 ina 就是这么判的). 用户从两个独立信号自己解读:
- ina 判 leans_feminine → 这是 F0-driven 分类的事实
- formant 判 F0_above_resonance → 这是共振峰独立测量的事实
- 不一致 = 用户的注意点, 不强行调和

### v3 启动条件

不在本设计中约束. 大体方向 (写在文档中供未来参考):
- Engine C 共振峰估计在 95 样本测试集上 ≥ 90% 样本输出 `formant_panel.reliability = "ok"`
- `decoupling_indicator` 在 cis_male_high_f0 类别上能区分 male_4 (F0_above_resonance) 与
  低 F0 cis_female (F0_resonance_aligned)

---

## §9 测试方案 (95 样本人工 review)

### 接口规约

新增 `tests/render_advice_v2.py` (本设计仅规约, 不实施):

```
输入:
  tests/fixtures/manifest.yaml

流程:
  对每个样本:
    1. 跑 Engine A (现有 do_segmentation) 获取 segments
    2. 跑 pyin[60-250] strict 获取 f0_panel 数据
    3. 计算 recording_duration_sec → 决定 gating_tier
    4. 调用未来的 advice_v2 计算函数 → 输出 advice dict
    5. 渲染为 markdown section

输出:
  tests/reports/advice_v2_render_<date>.md

每个样本一节, 包含:
  - 文件名 + ground truth label + manifest 标注的 F0
  - f0_panel JSON
  - tone_panel JSON (含 caveat_key 解析后的中英文文案)
  - summary_panel 文案 (中英文都渲染)
  - gating_tier
  - 人工 review 字段 (空白): "呈现是否合理? Y/N + 注释"
```

### 重点 review case 类别

| 类别 | 样本 | 预期 advice 输出 | 通过标准 |
|------|------|---------------|---------|
| 高基频 cis male (silent failure 历史) | `audio/male_4.wav` (manifest F0=176) | `f0_panel.median_hz≈172`, `range_zone="mid_neutral"`, `tone_tendency="leans_feminine"`, caveat 显式渲染 | 用户能从 caveat + 中性区间标注 + F0 数值自己解读出"分类不可靠"的可能 |
| 低基频 cis_female (over-correction 历史) | `audio/female_2.wav` (manifest F0=175) | `f0_panel.median_hz≈170`, `range_zone="mid_neutral"`, `tone_tendency="leans_feminine"`, caveat 同上 | tone_tendency 不被 cap 或修正; 不再有 "你被强制降到 Clear" 的隐式贬损 |
| 训练中 trans fem (HRT 进度) | `audio/trans_fem_early/synth_*.wav`, `audio/trans_fem_mid/synth_*.wav`, `audio/trans_fem_late/synth_*.wav` | F0 panel 显示 F0 进度 (HRT 等级越高 F0 越高), tone_tendency 随 margin 变化, summary 仅描述事实 | tone_tendency 在不同 HRT 阶段呈递进; summary 中无 "训练成功" / "已经像女声" 等评价语言 |
| 标准男声 (sanity check) | `audio/male_2.wav` | `range_zone="low"` 或 `mid_lower`, `tone_tendency="leans_masculine"`, caveat 仍显示 | caveat 在确定 case 上不被隐藏 |
| 标准女声 (sanity check) | `audio/female_3.wav` (F0=211) | `range_zone="mid_upper"`, `tone_tendency="leans_feminine"`, caveat 仍显示 | summary 文案模板齐全, 不掉落到 fallback |
| 极短录音 (gating sanity) | `audio/zh_10s.wav` 截短到 8s | `gating_tier="minimal"`, `tone_panel=null`, `summary_panel=null`, warning 显示 | 极短录音不会渲染 tone_tendency 或 caveat; F0 panel 仍尝试显示 (可能 reliability=short_recording) |
| 中等长度 (gating sanity) | `audio/zh_30s.wav` 截短到 18s | `gating_tier="standard"`, 完整 advice + warning 提示 30s 更稳 | warning 出现; 不掉 tone |
| trans masc 合成 (对偶 case) | `audio/trans_masc/synth_*.wav` | F0 中位数偏低, `tone_tendency` 视 margin 而定, caveat 同样适用 | trans masc 用户也获得 caveat 保护, 不被假设 ina 在低 F0 区间精确 |

### 通过门槛

- 任何**一个**上述 case 在 review 中被人工标 "呈现不合理", 即 block 实施
- 必须先迭代 schema / 文案 / 阈值, 重跑测试, 直到全部通过
- review 不评估**分类是否正确**, 只评估**呈现是否合理** (即 advice 输出对该 case 是否
  符合本设计文档的语义约束)

---

## §10 决策定稿 (2026-04-27 user 签字)

| # | 决策点 | 选定方案 | 理由 |
|---|--------|----------|------|
| 1 | F0 range_zone 边界 | **5 档, 130 / 165 / 200 / 240** | 不加第 6 档 (儿童 / 头声场景占比低, 增加 i18n 维护成本); `mid_neutral` 上界保持 200 与 caveat 文案 165-200 锚定 |
| 2 | tone tendency 阈值 | **单阈值 0.78** | 双阈值需要 confidence 概念, 与 "tone 不带数字" 原则矛盾 |
| 3 | caveat 是否带 Hz 数字 | **包含 (165-200)** | 用户能自行 verify ("我的 F0 在这个区间, 所以结果不可靠"); 引用 zone 标签更抽象, 对训练用户不直接 |
| 4 | minimal tier 是否显示 summary_panel | **不显示** | minimal tier 配 warning 条带 "录音少于 10 秒" 已经传达原因, 多一条 "无法生成解读" 文案是冗余 |

实施按本表锁定; 任何替代方案都需要重新 review.

---

## 实施 checklist (本设计批准后, 拆为单独 PR)

未在本次工作范围. 仅供未来实施参考.

后端:
- [x] `voiceya/services/audio_analyser/__init__.py` `do_analyse` 在 `summary` 下追加 `advice` 字段
- [x] 新增 `voiceya/services/audio_analyser/advice_v2.py`: 纯函数 `compute_advice(...) → dict`
- [x] 新增 `voiceya/services/audio_analyser/f0_panel.py`: `pyin[60-250]` + `voiced_flag` (viterbi-smoothed)
- [x] `statics.py` 不动 (`female_ratio` 等顶层字段保留)

前端:
- [x] `web/src/modules/i18n.js` 新增 26+ 个 i18n key (caveat 1 + tone 3 + zone 5 + summary 15 + warning 2 + UI 标题), zh-CN + en-US; 删除已废弃 `certainty.*` 10 个 key
- [x] `web/src/utils.js` `certaintTag()` 重定义为 3 档 mapper, 阈值 0.78 与后端一致
- [x] `web/src/modules/metrics-panel.js` 新增 `renderAdvicePanel` / `clearAdvicePanel`
- [x] `web/index.html` 在右侧 aside 加入 `#advice-panel` DOM 块 (caveat / f0 / tone / summary / warning)
- [x] `web/src/styles/main.css` 加 `.advice-panel` 系列样式 (含 mid_neutral zone 高亮)
- [x] `web/src/main.js` result handler / history restore / lang change 三处都调 `renderAdvicePanel`

测试:
- [x] 新增 `tests/render_advice_v2.py` 95 样本批量渲染脚本
- [x] 新增 `tests/test_advice_v2.py` 16 个单元测试 (zone / gating / tendency / distribution / schema)
- [x] 输出 `tests/reports/advice_v2_render_2026-04-27.md` (基线), 待人工 review

文档:
- [x] 本文件 (`docs/plans/v2_redesign_measurement.md`)
- [x] `CLAUDE.md` 加 "Advice v2 输出 schema" 段, 指向本文档

---

## 关联资料

- 数据基础: `tests/reports/category_eval_2026-04-27.md` (95 样本 margin / F0 分布)
- Stress test: `tests/stress_f0_window.py` (file_F0_strict 长度稳定性)
- v2.5 历史决策: `docs/plans/advice_v2_conservative.md` (本文档 supersedes)
- 已知样本局限: `tests/fixtures/KNOWN_LIMITATIONS.md` (合成样本不能用于阈值标定)
- Engine A T=2.0 实现: `voiceya/inaSpeechSegmenter/inaSpeechSegmenter/segmenter.py:194-199, 266`
- C1 margin 实现: `voiceya/inaSpeechSegmenter/inaSpeechSegmenter/segmenter.py:223`
- i18n 协议: `voiceya/services/sse.py:62-69` (`msg_key` + `msg_params` 后端模式),
  `web/src/modules/i18n.js:686-691` (`t(key, params)` 前端模式)
