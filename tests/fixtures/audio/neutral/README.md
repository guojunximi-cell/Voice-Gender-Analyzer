# neutral

性别中性声音（Gender-Neutral / Androgynous Voice）。

## 定义与 F0 范围

此类别涵盖 F0 落在男女重叠区间（约 145–185 Hz）、且声道特征也处于中间区域的声音。
来源可以是顺性别者（高音男性、低音女性）或非二元性别者。

| 指标 | 典型值 |
|------|--------|
| F0 中位数 | 140–195 Hz |
| F0 范围 | 115–230 Hz |
| 声道长度（VTL） | 15–18 cm |
| 共振峰 F2 | 1300–1900 Hz |

**关键特征**：
- F0 处于 Engine A 判断边界（150–185 Hz 是模型最不确定区间）
- VTL 也处于中间区域（非极端男性也非极端女性）
- 此类别是 Engine A "应该不确定"的声音——低 margin 在此不是 bug，是正确行为
- **主要用途：量化模型的"可接受不确定性"下界**

## 推荐公开数据源

### 顺性别低音女性

- **VCTK** 低音区女性说话人：
  | Speaker | F0 中位数（约） | 备注 |
  |---------|--------------|------|
  | p231 | ~168 Hz | 较低女声 |
  | p233 | ~172 Hz | 较低女声 |
  | p335 | ~165 Hz | 较低女声 |

- **LibriTTS** 女性 speaker：筛选 F0 中位数在 155–180 Hz 的样本
  ```bash
  python3 -c "
  import librosa, numpy as np, glob
  for f in sorted(glob.glob('LibriTTS/test-clean/*//*.wav'))[:200]:
      y, sr = librosa.load(f, sr=None)
      f0, _, _ = librosa.pyin(y, fmin=80, fmax=350, sr=sr)
      mf = np.nanmedian(f0)
      if 155 < mf < 185:
          print(f'{f}  F0={mf:.0f} Hz')
  " | head -20
  ```

### 非二元性别者

- **TGVC** 中 `nonbinary` 子集（如存在）
- 公开表示非二元身份的播客/YouTube 创作者（需书面许可）

### 顺性别高音男性（参见 cis_male_high_f0 类别）

F0 在 145–180 Hz 的高音男性声音也归入此类别，形成对比：
- 参考：`../cis_male_high_f0/README.md`

## 录音质量要求

与 `cis_female/README.md` 相同。额外字段（manifest.yaml 中）：

- `notes` 字段记录：说话人自述性别身份（如愿意披露）、F0 来源（顺性别低音女/高音男/非二元）

## 期望测试结果

```
C1-T2.0 margin：mean 0.25–0.55（此类别 margin 低是正确的）
分类准确率：无有意义的"正确率"概念（ground_truth_label 可标 neutral）
主要用途：
  - 验证 Engine A 在边界区确实输出低 margin（而不是随机高置信误分类）
  - 为 advice 系统 "boundary" 条件的触发阈值提供校准数据
  - margin < 0.30 的样本比例应 > 40%（这是正确行为，不是模型故障）
```
