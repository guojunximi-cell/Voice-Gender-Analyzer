# cis_male_high_f0

顺性别高基频男性说话人（Cisgender Male, High F0）。

这是 **male_4.wav 类型**：声带生理结构为男性，但基频落在女性范围，导致 Engine A 高置信度误分类。

## 定义与 F0 范围

| 指标 | 典型值 |
|------|--------|
| F0 中位数 | 145–210 Hz |
| F0 范围 | 130–240 Hz |
| 声道长度（VTL） | 16–18 cm（偏男性，即使 F0 高） |
| 共振峰 F2 | 1200–1700 Hz（低于女性均值） |

**关键特征**：F0 高但 VTL/共振峰仍偏男性。这是 Engine A 的已知 bias 区间（该模型训练集高音男声样本不足）。

此类别的预期结果是 **Engine A 频繁误分类** ——这不是测试失败，而是记录模型局限性。

## 实测结果（2026-04-27, T=2.0）

| 文件 | F0 中位数 | 分类准确率 | C1-T2.0 margin | 结论 |
|------|---------|----------|----------------|------|
| male_1.wav（真实） | 174 Hz | 43% | 0.571 | **系统性误分类，非孤立案例** |
| male_4.wav（真实） | 176 Hz | 0% | 0.883 | 原始 bias case，已证实 |

**结论：Engine A 对高 F0 男声的误分类是系统性的，不是 male_4 孤立现象。**
male_1（不同录音来源）同样出现 57% 误分类率，印证了模型训练集在 145–200 Hz 男声样本上存在结构性不足。

### 合成样本的局限性

sox `pitch` 命令同时移动 F0 和共振峰（速度变调而非声码器分离），导致合成高音样本
的共振峰也进入女性范围，Engine A 将其分类为 female 是"正确行为"而非 bias 的体现。
合成样本不能代替真实高音男声来验证 F0/共振峰解耦 bias。

## 推荐公开数据源

### VCTK（需实测 F0 筛选）
以下说话人 F0 偏高，可能进入该类别（需验证）：

| Speaker | 语言/口音 | F0 中位数（约） | 验证状态 |
|---------|---------|--------------|--------|
| p254 | English (SSE) | ~155 Hz | 待验证 |
| p255 | English (SSE) | ~150 Hz | 待验证 |
| p274 | English (SSE) | ~162 Hz | 待验证 |
| p286 | English (SSE) | ~158 Hz | 待验证 |

**筛选方法**：
```bash
# 用 librosa 批量测量 VCTK 男性说话人的 F0
python3 -c "
import librosa, numpy as np, glob
for f in sorted(glob.glob('VCTK/wav48_silence_trimmed/p*/p*_001_mic1.flac')):
    y, sr = librosa.load(f, sr=None, mono=True)
    f0, _, _ = librosa.pyin(y, fmin=60, fmax=400, sr=sr)
    mf = np.nanmedian(f0)
    if 145 < mf < 220:
        print(f'{f}  F0={mf:.0f} Hz')
"
```

### CommonVoice
- 筛选条件：`gender=male`，`age=twenties` 或 `thirties`
- 上传 F0 > 145 Hz 的男性录音
- 注意：CommonVoice 说话人身份不可验证，需结合 VTL 估算做二次筛选

### 东亚语系 TTS 数据集
- 东亚男性（中文、日文、韩文）平均 F0 偏高（常见 130–170 Hz），比西方数据集更容易找到高音男声
- **AISHELL-3** 中选 F0 > 145 Hz 的男性 speaker（SSB 前缀中筛选）
- **JVS（Japanese Voice Corpus）**：`https://sites.google.com/site/shinnosuketakamichi/research-topics/jvs_corpus` 日本男性多有 F0 高于均值的样本

### 现有样本
- `../male_4.wav`（flat 目录）：已测 C1-T1=0.928，C1-T2=0.883，被误标 female —— 此样本是此类别的原始动机

## 录音质量要求

与 `cis_female/README.md` 相同，额外要求：

- **每个说话人附带 praat 测量截图**（F0 均值 + VTL 估算），作为 ground truth 的声学佐证
- 时长建议 ≥ 20 秒（需要足够多帧验证 margin 分布的宽度）

## 期望测试结果

```
C1-T2.0 margin：mean 0.70–0.90（高于 cis_male_standard 均值）
分类准确率（label=male）：预计 < 50%（engine A 的已知 bias）
主要用途：量化误分类的 margin 区间，为 advice 重构提供 reject 阈值依据
```
