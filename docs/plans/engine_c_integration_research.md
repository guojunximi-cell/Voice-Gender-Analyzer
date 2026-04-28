# Engine C (Praat) 集成可行性调研

> 仅调研，不写代码、不写实施方案。
> 测试硬件：项目 .venv（Python 3.13.13），WSL2 / Linux 6.6，无 GPU。
> 测试集：`tests/fixtures/audio/`，53 个 WAV 文件，总时长 855.4 s（min 3.0s / median 3.9s / max 57.2s）。
> 调研日期：2026-04-27。

---

## 起因（context recap）

测试集分类型评估证实 inaSpeechSegmenter（Engine A）在高基频男声（F0 ~170-180 Hz）上系统性误分类——
不是 male_4 一个孤立 case：

| 文件 | F0（pyin[60-250]） | Engine A 准确率 | C1-T2.0 margin |
|------|------|------|------|
| male_1.wav | 174 Hz | 43% | 0.571 |
| male_4.wav | 176 Hz | 0% | 0.883 |

advice 系统不能纯靠 Engine A 的 label/置信度作判据。需要一个独立的声学信号做 sanity check。
最朴素的候选是 F0：Engine A 说"male"但 Praat F0 在 170+ Hz 时，提示 advice "Engine A 信号可能不可靠，谨慎给建议"。
本调研评估这条路是否可行。

---

## 1. Praat 调用方式

### 1.1 项目里 Engine C 的现状（不是空白，但和这次需求不是一回事）

**已实现**（`voiceya/services/audio_analyser/engine_c.py`，329 行 + sidecar）：

- 重型管线：ASR（FunASR Paraformer-zh / faster-whisper）→ MFA forced alignment → Praat 共振峰 → 音素级 z-score。
- Praat 调用方式：**subprocess** 调原生 `praat --run` CLI，不是 parselmouth。脚本在
  `voiceya/sidecars/visualizer-backend/textgrid-formants.praat`，关键两行：
  ```praat
  To Pitch: 0, 75, 600
  To Formant (burg)... 0 5 5000 0.025 50
  ```
- 部署形态：独立 Docker sidecar（`engine-c` profile），镜像 ~2.5 GB（含 MFA 模型、ASR、Praat），首次构建 10 分钟。
- 默认关闭：`ENGINE_C_ENABLED=false`。失败时 `summary.engine_c = None`，不影响 A/B 主响应。
- 触发条件：voiced 总时长 ≥ `engine_c_min_duration_sec`，全段一次性送 sidecar，不按 VAD 段切。
- 输出：phone-level dict，含 `pitch`、`F1/F2/F3`、`resonance`，前端目前未消费。

> **结论**：现有 Engine C 不能直接复用做"per-segment F0 sanity check"。它需要 ASR + MFA 才能跑，
> 重量级、装在另一个容器、对短录音/无脚本时延高，并且产出的是音素级而不是段级数据。
> 本次需求要的是**第二种 Praat 集成**：worker 进程内的 parselmouth 调用，按 Engine A 段切，只算 F0
> 中位数（可选 formant），与 sidecar 那条路不冲突也不依赖。下文都按这条新路调研。

### 1.2 parselmouth API（实测可用）

`praat-parselmouth==0.4.7` 是 Praat 的 Python 绑定，pip 安装、~10 MB wheel、纯 C++ 后端、不需 subprocess。
项目 .venv 当前没装；调研用 `uv run --with praat-parselmouth` 跑。

**最小用法（F0）**：

```python
import parselmouth
import numpy as np

# y: float32/float64 mono samples; sr: int Hz
snd = parselmouth.Sound(values=y.astype(np.float64), sampling_frequency=sr)
pitch = snd.to_pitch(time_step=None, pitch_floor=75.0, pitch_ceiling=600.0)
f0 = pitch.selected_array["frequency"]   # ndarray, 0 = unvoiced
voiced = f0[f0 > 0]
f0_median = float(np.median(voiced)) if len(voiced) else None
```

注意 `time_step=None`（不能写 0.0，签名要求 `Optional[Positive[float]]`）→ Praat 默认 `0.75 / pitch_floor`，
75 Hz floor 时 = **10 ms 帧步**。

**Formant**：

```python
formant = snd.to_formant_burg(
    time_step=None,                # 默认 = window_length / 4 = 6.25 ms
    max_number_of_formants=5,
    maximum_formant=5000.0,        # 男声推荐 5000，女声 5500
    window_length=0.025,
    pre_emphasis_from=50.0,
)
f1_at_t = formant.get_value_at_time(1, t_seconds)   # NaN 表示该时刻无可信 formant
```

跟现有 `acoustic_analyzer.py:74 _extract_formants` 的 LPC 路径概念一致，但 Praat 的 Burg LPC 实现比项目里
`scipy.linalg.solve_toeplitz` + `np.roots` 更稳（自带带通、根稳定性筛选）。

### 1.3 与 inaSpeechSegmenter 时间轴对齐（直接、无需 MFA）

Engine A 输出 `segmentation_results: list[tuple]`，每条 = `(label, start_time, end_time, confidence?, ...)`。
现有 `seg_analyser.py:79-82` 已经在做 sample-level 切片：

```python
start = int(r.start_time * sr_full)
end = int(r.end_time * sr_full)
y_seg = y_full[start:end]
```

要做 per-segment Praat F0 中位数，只需要：

1. 对每个 `_is_analyzable`（label∈{female,male} 且 duration≥0.5s）的段切 `y_seg`；
2. `parselmouth.Sound(values=y_seg, sampling_frequency=sr_full)` 构 Sound；
3. `.to_pitch()` → 取 voiced F0 中位数；
4. 挂到 `AnalyseResultItem.acoustics` 同级的新字段（如 `praat_f0_median_hz`）。

**对齐误差**：Praat F0 帧步 10 ms，与 Engine A VAD 段边界精度（约 ±50 ms，CNN 滑窗决定）兼容。
不需要 MFA、不需要 ASR、不需要文本——这是和现有 Engine C sidecar 的根本区别。

---

## 2. 时间分辨率

### 2.1 默认帧率

| 阶段 | 默认 time_step | 实际值（默认参数） |
|------|------|------|
| `to_pitch(pitch_floor=75)` | `0.75 / floor` | **10 ms** |
| `to_formant_burg(window_length=0.025)` | `window/4` | **6.25 ms** |

10 ms 步长意味着：

- 0.5 s 段 → ~50 帧
- 1.0 s 段 → ~100 帧
- 3.0 s 段 → ~300 帧

中位数估计的统计稳定性主要看 voiced 帧数。0.5 s 段在普通对话语速下 voiced 比例 60-80%，
实际有效帧 30-40 个，标准误差 ≈ σ_F0 / √N ≈ 15/6 = 2.5 Hz——比 Engine A bias 区间宽度（170-180 vs 阈值）
小一个量级，**单段 0.5s 的 F0 中位数足够稳定**。

实测（53 文件，时长 3-57s）：所有文件 voiced 帧数 ≥ 161，最低就是 cis_male_high_f0 里的 3.92 s synth 样本。
没有任何样本因帧数不足落到 None。

### 2.2 噪声 / silence 影响

Praat `to_pitch(ac)` 用自相关 + voicing 判决。silence 段 voicing 为 0，会被自动过滤（不进 voiced[f0>0] 子集）。
低 SNR 场景下：

- 白噪音背景：voicing 阈值降一档，会有少量假 voiced 帧（F0 随机散点），对中位数影响小（< 5 Hz）；
- 旋律/音乐背景：autocorrelation 会**锁到伴奏的最强周期**，F0 中位数被音乐拉走——这是已知失败模式（详见 §4）；
- ffmpeg silencedetect 已经在 sidecar 用过（-30 dB / 0.5 s），同样的策略可以前置过滤掉纯 silence 段。

**对本次需求**：sanity check 只需要"段内 voiced F0 中位数"，不需要 jitter/shimmer。
中位数对噪声鲁棒性已经足够。

---

## 3. 计算开销（实测）

测试方法：53 个测试集 WAV 全文件载入（不切 VAD 段）+ Praat F0 + Praat Formants，记录 wall time。

```
=== Audio durations (seconds) ===
  min=3.00  median=3.88  max=57.22  total=855.4s

=== Praat F0 (To Pitch ac, 0/75/600) — wall time ===
  min=0.0020  median=0.0032  max=0.0243  sum=0.406s

=== Praat Formants (Burg) — wall time ===
  min=0.0163  median=0.0231  max=0.3656  sum=5.524s

=== Per-second-of-audio cost ===
  Praat F0:        0.48 ms / s of audio
  Praat Formants:  6.46 ms / s of audio
  F0 + Formants:   6.93 ms / s of audio
```

### 3.1 与 Engine A 总时间的比例

Engine A（inaSpeechSegmenter Keras CNN，CPU）典型耗时 ~5-10 s / 60 s 音频（CLAUDE.md 没记，参考
`voiceya/inaSpeechSegmenter/run_test.py` 的样本大致估算）。一个 60 s 录音：

| 工序 | 时间 | 占 Engine A 比例 |
|------|------|------|
| Engine A | ~5000-10000 ms | 100% |
| Praat F0（全段一次） | ~30 ms | **~0.3-0.6%** |
| Praat F0+Formant | ~420 ms | ~4-8% |
| 现有 Engine B（pyin+LPC） | ~1500-3000 ms（项目内已观察） | ~15-50% |

**F0-only 的开销可忽略**。Formant 也只是 Engine B 的 ~30%。如果按 VAD 段切（典型 5-10 段），
parselmouth 每段都要重建 Sound 对象，但每段耗时 < 5 ms，53 段总时长 855 s 跑全文件用了 5.5 s——
即使粗略加倍到 10-11 s 估计 segment-by-segment 模式，也仍远低于 Engine A 本身。

### 3.2 是否能默认开启

**F0-only：可以默认开启**。30 ms / 60s-文件 用户根本感知不到。
**F0 + Formant：可以默认开启，但要量一下**。380 ms / 60s 还在容忍范围（Engine A 占主导，进度条也是
按 Engine A 推进），但需要注意：

- librosa.load 第一次调用有 1.56 s 冷启（torch/scipy 等模块解压），这次实测是首文件偏差，已经在 worker 启动时通过 Engine A/B 的 librosa 调用 amortize 掉了，对现有架构没新开销。
- parselmouth 模块 import 本身也要计时——补一次启动 import 测量是 P1 工作，不阻碍 go/no-go 决策。

UX 不会退化。

---

## 4. 失败模式

### 4.1 Praat F0 不可靠的 4 种典型场景

| 场景 | 行为 | 对 sanity check 的影响 |
|------|------|------|
| 耳语（whisper）| 无声门振动 → 无 voicing → F0 全 0 → 中位数 None | 落到 fallback；不会假冲突，但 sanity check 信号缺失 |
| 喉化/creaky voice（vocal fry）| 不规则声门脉冲；自相关锁到 2× 真 F0 → octave doubling | **会假冲突**：真 80 Hz 男声被报成 160 Hz，触发"高 F0 → 拒 male verdict"误判 |
| 低 SNR 背景音乐 | autocorrelation 锁伴奏旋律 | F0 跟伴奏走，跟说话人无关；可能任意方向假冲突 |
| Pitch ceiling 内的 octave error | 男声二倍频落在 ceiling 内时被选中 | **本次需求最致命的失败模式**，详见 §4.2 |

### 4.2 ⚠️ 关键发现：male_4 的 F0 自身就不可靠

实测在 male_4.wav 上跑不同 ceiling 的 Praat：

```
=== male_4.wav ===
  Praat [75-600]:  median=288.7  voiced_frames=3174
  Praat [75-400]:  median=282.5  voiced_frames=3182
  Praat [75-300]:  median=196.7  voiced_frames=3124
  Praat [75-250]:  median=166.3  voiced_frames=3059
  pyin  [60-500]:  median=302.3
  pyin  [60-250]:  median=215.0
```

manifest 把 male_4 的 ground-truth F0 标成 176 Hz（pyin[60-250] 实测），但**两种主流 F0 算法（Praat AC、pyin）
在 ceiling 放宽时都给出 280-300 Hz 的octave-doubled 估计**。manifest 注释也承认这点：
`"pyin[60-400] shows octave errors at 287Hz"`。

把这个对照 male_1：

```
=== male_1.wav ===
  Praat [75-600]:  median=167.5
  pyin  [60-250]:  median=168.7
```

male_1 的 F0 算法稳定，但中位数 167-176 已经在 cis_female 的下沿（manifest 里 female_2/_5 都标 175 Hz）。
**naive 的"F0 > 165 Hz → 拒 male verdict"会同时误杀 cis_female 和"救"male_1，但对 male_4 完全无效**——
因为 male_4 的 F0 估计本身就在 290 附近，sanity check 会和 Engine A 一起说"这是 female"，反向加固误判。

### 4.3 假冲突会不会误触 advice 拒绝

会，且来源不止 octave error 一种：

- creaky voice 男声：真 F0 80 Hz，octave-doubled 到 160 Hz，sanity check 误报"高 F0"，advice 莫名拒绝；
- 早期 trans fem 阶段（manifest 里 trans_fem_early/synth_early_*）F0 已经训上去但其余声学还没跟上，
  Engine A 大概率仍输出 male——这正是用户期望 sanity check 介入的场景，但 sanity check 同时也会对
  creaky cis male 误报，无法区分；
- pitch-shifted 攻击样本（adversarial roadmap ATK-3）：Engine A 看 envelope，sanity check 看 F0，
  二者必然冲突，触发 advice 拒绝——这反而是预期行为。

**净效应**：F0 sanity check 减少 male_1 类（F0 真高的 cis male）误判，代价是引入 creaky voice cis male
和合成攻击样本的"健康人也被拒"，并对 male_4 类完全失效。是否净改善取决于真实流量分布——本次调研无法回答。

---

## 5. 不解决的问题

### 5.1 F0 区分不了的场景

| 场景 | F0 表现 | 真实声学差异 |
|------|------|------|
| 训练成功的 trans woman（pitch 上去了，formant 没上去） | F0 ~220 Hz（女范围） | VTL ~17 cm（男范围）；F1/F2 偏低 |
| 训练失败的 trans woman（F0 没上去） | F0 ~120 Hz（男范围） | VTL ~17 cm |
| male_4 类（F0 已经比女性中位数还高） | F0 ~290 Hz | VTL/F2 仍是男范围 |
| 假声（falsetto）男性 | F0 ~250+ Hz | 共振结构和模态嗓不同，但 VTL 还是男 |

**F0 sanity check 不能取代 formant**。它只能告诉你"Engine A 和 F0 矛盾"，不能告诉你哪一个是对的；
也不能告诉你 trans-fem 用户的训练进度（pitch vs resonance 哪个落后）。
EDGE-C（Engine C roadmap doc 里 P0 的 "高音 + 未训共振" case）必须有 formant/VTL 才能有意义地诊断。

### 5.2 Formant 在 < 1s 段的稳定性

- Praat formant_burg 默认 25 ms 窗 + 6.25 ms 步：1 s 段 ≈ 160 帧，0.5 s 段 ≈ 80 帧。
- 但**整段中位数没有声学意义**：F1/F2 是元音特征，不是嗓音常数；同一说话人 /a/ 的 F1 ~700 而 /i/ 的 F1 ~270，
  跨元音求中位数得到的数和 VTL 的关系会被语料音素分布稀释。
- 现有 sidecar 的做法是 MFA 对齐到音素，**只在元音 midpoint 取 formant**。worker 进程内做 parselmouth-only 集成
  没有 MFA，要在不知道音素的情况下取 formant median，必须做某种"伪元音检测"——可选方案有：
  - F1 + F2 落在元音三角内的帧才采（启发式，会漏边缘元音）；
  - 高能量稳态帧（energy + RMS-stability gate）；
  - silero VAD + spectral entropy 选 sonorant 帧。

  以上都是研究问题，不是工程问题。短段（< 1 s）尤其敏感：如果该段恰好 dominated by 一个 fricative，
  median F1/F2 就是噪声。

**结论**：worker 进程内、不接 MFA 的 formant sanity check **现阶段不可行**。要 formant，
要么把现有 Engine C sidecar 跑起来（重型），要么投入研究做轻量级元音检测。

---

## 末尾事实陈述

### Q1: Engine C 集成的工程难度

**分两个粒度**：

1. **Worker 进程内 parselmouth F0-only sanity check**（本调研主要评估的方案，独立于现有 sidecar）：
   - **小时级到一天**。`uv add praat-parselmouth` → 在 `seg_analyser.py:67` 已有的 `_is_analyzable` 分支里
     补 ~30 行 `parselmouth.Sound(...).to_pitch()` → 新字段挂到 `AnalyseResultItem` → 改 SSE schema 同步前端字段
     （前端可零改，后端单字段加上即可）→ 加测试。`acoustic_analyzer.py` 已经处理 F0 None-fallback 的形状，
     沿用同样的 graceful skip。
   - 主要时间花在测试覆盖 + advice 逻辑的"如何使用 sanity check 信号"，那是另一个 PR 的事。

2. **Worker 进程内 parselmouth F0 + Formant sanity check**：
   - **天级到周级**。F0 部分同上，formant 部分卡在 §5.2——必须先解决"段内取 formant 的元音定位"研究问题。

3. **复用现有 Engine C sidecar 给每段供 F0/formant 数据**：
   - **天级**。架构上 sidecar 已经能跑，但它是整段一次、需要 ASR/MFA、~2.5 GB 镜像。
     要按 VAD 段切多次调用 sidecar，得改 sidecar API，并接受 worker→sidecar 的 N 次 HTTP 来回开销。
     做这件事的理由不强——既然进程内 parselmouth 一行能解决 F0，没必要把 sidecar 强行塞进 sanity-check 路径。

**推荐路径**：先做 1（F0-only），观察 advice 效果，再决定要不要投资 2（formant）。

### Q2: 哪些 male_high_f0 误判 case 能被 F0 sanity check 抓到

- **male_1.wav（F0=167-174 Hz）**：能抓到。Praat[75-600] 给 167，与 pyin 一致，落在 cis_female 下沿但仍可
  作为"Engine A 信号可能不可靠"的提示。advice 不必反转 verdict，只要降权或加免责声明。
- **真实未训练高音 cis male（F0 145-200 Hz 区间，无 octave 异常）**：能抓到，性质同 male_1。
  这是 manifest 推荐 VCTK p254/p255/p274/p286 与东亚男性数据集要补的样本类型。
- **trans fem early（manifest 里的 synth_early_*）**：能抓到（F0 160-250），且这是用户期望 sanity check
  正向触发的场景。代价见下条。

### Q3: 哪些 case 即使加 Engine C（F0-only）也抓不到

- **male_4.wav 类（F0 真高且 octave-double 严重）**：抓不到。Praat 默认设置给 289 Hz，
  比 cis_female median（190 Hz）还高，sanity check 会和 Engine A 一起说"是 female"，**反向加固误判**。
  要救这类只能：(a) 把 ceiling 拉到 250，但同时砸掉 cis_female；或 (b) 加 octave-jump 检测，
  非 trivial。无 formant 信号无解。
- **训练有成的 trans woman（pitch 已升、formant 未跟）**：F0 sanity check 不会触发任何冲突
  （Engine A 看 envelope 多半给"male"或低置信"female"，F0 给"female"），冲突方向是
  "Engine A 偏男 vs F0 偏女"，sanity check 只能说"信号可能不可靠"——但用户最想要的"resonance/VTL 反馈"
  完全给不出来。**这是 EDGE-C 的核心，F0-only 路径永远解决不了**。
- **vocal fry / creaky voice cis male**：sanity check 会因 octave-doubling 误以为高 F0，
  对 Engine A 正确的 male verdict 假冲突。要救 EDGE-B（vocal fry）就要提供 fry 检测，又是另一个工作流。
- **耳语录音、低 SNR 背景音乐、合成 pitch shift 攻击**：F0 信号本身无效或被污染，sanity check 输出
  噪声而不是信息。
- **mixed register 在一段录音里（EDGE-A）**：per-segment F0 中位数会按段给出双峰，但这变成"前端怎么呈现
  时间轴"的问题，sanity check 单值聚合反而把信号丢了。
