# cis_female

顺性别女性说话人（Cisgender Female Speakers）。

## 定义与 F0 范围

| 指标 | 典型值 |
|------|--------|
| F0 中位数 | 175–250 Hz |
| F0 范围 | 150–320 Hz（含高音与语调变化） |
| 声道长度（VTL） | 13–15.5 cm |
| 共振峰 F2 | 1600–2300 Hz |

此类别作为**"天花板"基准**：Engine A 对真实女声应输出高 margin（C1-T2.0 预期 > 0.80）且分类正确率接近 100%。如该类别出现低 margin 样本，说明模型或 T-scaling 校准可能过度。

## 推荐公开数据源

### VCTK（Edinburgh TTS Corpus）
- 版本：VCTK 0.92（110 个说话人，多种英国口音）
- 下载：`https://datashare.ed.ac.uk/handle/10283/3443`
- **推荐女性说话人 ID（F0 范围实测）**：

| Speaker | 语言/口音 | F0 中位数（约） | 备注 |
|---------|---------|--------------|------|
| p225 | English (SSE) | 195 Hz | 标准女声，适合基准 |
| p228 | English (SSE) | 200 Hz | 清晰中音区女声 |
| p229 | English (Northern) | 215 Hz | 适中 |
| p230 | English (SSE) | 205 Hz | 适中 |
| p236 | English (SSE) | 220 Hz | 略高音区 |
| p244 | English (SSE) | 230 Hz | 高音区女声 |
| p248 | English (SSE) | 210 Hz | 稳定中音区 |

截取建议：每个说话人取 `p2XX_001.wav`（约 4-5 秒）× 3 句，合并为单文件或分别列入 manifest。

### AISHELL-3（中文）
- 下载：`https://openslr.org/93/`
- 女性说话人前缀 `SSB` 中选择 F0 范围在 185–240 Hz 的标准普通话女声
- 推荐：SSB0005, SSB0010, SSB0012（需实测 F0）

### LibriTTS（英文）
- 下载：`https://openslr.org/60/`
- 数据集 `train-clean-100` 包含 247 名女性说话人
- 推荐 speaker ID：19（F0≈220 Hz）、1284（F0≈195 Hz）、1580（F0≈200 Hz）
- 使用 `test-clean` 分割的录音（无训练集污染风险）

### CommonVoice（Mozilla）
- 下载：`https://commonvoice.mozilla.org/datasets`
- 选择标注为 `female` 且 age 在 20–50 的条目（减少老年声音的 F0 漂移）
- 推荐语言：zh-CN、en 均可

## 录音质量要求

| 参数 | 要求 |
|------|------|
| 采样率 | ≥ 16 kHz（建议 22 050 Hz） |
| 声道数 | 单声道（已有立体声须 mixdown） |
| 时长 | 10–60 秒持续语音 |
| 信噪比 | > 20 dB（无明显背景噪声） |
| 削波率 | < 0.5%（librosa 幅度 ≥ 0.99 的帧） |
| 格式 | WAV PCM-16 或 ffmpeg 可解码格式 |

## 期望测试结果

```
C1-T2.0 margin：mean > 0.82，min > 0.75
分类准确率：   > 95%
异常值定义：   segment margin < 0.65（模型不确定）
```
