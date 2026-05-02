# cis_male_standard

顺性别男性说话人，F0 在标准男性范围内（Cisgender Male, Standard F0）。

## 定义与 F0 范围

| 指标 | 典型值 |
|------|--------|
| F0 中位数 | 85–145 Hz |
| F0 范围 | 70–160 Hz |
| 声道长度（VTL） | 17–19 cm |
| 共振峰 F2 | 1000–1500 Hz |

此类别是**"地板"基准**：Engine A 对标准男声应输出高 margin 且标签为 male。注意此类别 F0 上界 145 Hz 与 trans_fem_early（100–155 Hz）的上界有交叠，分界依据是说话人身份而非纯粹声学测量。

## 推荐公开数据源

### VCTK
- **推荐男性说话人 ID**：

| Speaker | 语言/口音 | F0 中位数（约） | 备注 |
|---------|---------|--------------|------|
| p226 | English (SSE) | 120 Hz | 标准中音男声 |
| p227 | English (SSE) | 108 Hz | 标准低音男声 |
| p232 | English (Scottish) | 118 Hz | 标准男声 |
| p256 | English (SSE) | 125 Hz | 稳定中音区 |
| p258 | English (SSE) | 112 Hz | 低中音 |
| p260 | English (SSE) | 105 Hz | 低音男声 |
| p270 | English (SSE) | 118 Hz | 中音男声 |
| p271 | English (SSE) | 98 Hz | 标准低音 |

### CMU ARCTIC
- 下载：`http://www.festvox.org/cmu_arctic/`
- 推荐：`BDL`（男，F0≈115 Hz）、`RMS`（男，F0≈122 Hz）、`JMK`（男，F0≈107 Hz）
- 每个说话人约 1150 句，取 `arctic_a0001.wav` 至 `arctic_a0010.wav` × 3 个说话人足够

### AISHELL-1/3（中文）
- 下载：`https://openslr.org/33/`（AISHELL-1）
- 男性说话人前缀 `S` 中选择 F0 实测 < 140 Hz 的样本
- 推荐：S0002, S0003, S0015（需实测 F0）

### LibriTTS
- 推荐男性 speaker ID：260（F0≈107 Hz）、4077（F0≈110 Hz）、4446（F0≈115 Hz）

## 录音质量要求

与 `cis_female/README.md` 相同。

## 期望测试结果

```
C1-T2.0 margin：mean > 0.80，min > 0.65
分类准确率：   > 95%（注意：F0 140–160 Hz 区域准确率可能偏低）
异常值定义：   margin > 0.85 且 label=female（潜在高音男声误判）
```
