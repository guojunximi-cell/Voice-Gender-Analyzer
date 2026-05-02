# trans_fem_mid

MTF（Male-to-Female）跨性别者嗓音训练中期。

## 定义与 F0 范围

训练 6–18 个月，有系统训练记录。声音特征开始向女性方向迁移，但仍处于过渡区间。

| 指标 | 典型值 |
|------|--------|
| F0 中位数 | 155–200 Hz |
| F0 范围 | 130–240 Hz |
| 声道长度（VTL） | 16–18.5 cm（共振峰训练开始影响 VTL 感知） |
| 共振峰 F2 | 1450–1900 Hz（有意识上移中） |

**关键特征**：
- F0 进入过渡区（150–200 Hz 为 Engine A 最不确定的区间）
- 共振峰开始受训练影响但尚未稳定
- 语调模式（intonation）可能已部分女性化，但 F0 底线未变
- Engine A 预期在 male/female 之间摇摆，同一句话内可能出现不同标签
- **此类别是验证 advice 系统"鼓励性中间段"措辞的关键测试集**

## 推荐公开数据源

### 注意事项

与 trans_fem_early 相同——数据极度稀缺，使用前必须确认授权和知情同意。中期声音因个体差异极大，采集时需明确记录训练时长。

### 学术数据集

| 来源 | 内容 | 获取方式 |
|------|------|---------|
| **TGVC（Trans Gender Voice Corpus）** | 如含训练进度标注，中期子集最有价值 | https://github.com/TransVoiceLab（如已公开） |
| **Arantes 等（2020）** | "Pitch and Resonance Modification in MTF Trans Voices" 附小型纵向数据 | 联系论文作者 |

### 社区来源（公开许可）

- **YouTube 嗓音训练进度视频**（"3 months HRT voice", "6 months training progress" 等关键词）
  - 仅使用视频创作者明确声明 CC 许可或书面同意的内容
  - 重点关注声明训练时长（6–18 个月）的视频
- **r/transvoice** "progress check" 帖：有时贴主会声明"随意使用，不需标注"

### 合成近似（临时占位）

```bash
# 对 cis_male_standard 做基频上移 +50 Hz（pitch shift）
# 注意：不改变共振峰，声学近似程度低于真实训练声音
sox input.wav output.wav pitch +700   # 约 +50 Hz
```

标注 `notes: synthetic_pitch_shift_50hz`，不混入真实数据分析。

## 录音质量要求

与 `cis_female/README.md` 相同。额外字段（manifest.yaml 中）：

- `notes` 字段记录：HRT 月数（如已知）、训练课程类型（自学/教练）、训练开始时间（年月）

## 期望测试结果

```
C1-T2.0 margin：mean 0.40–0.70（分布最宽，最接近均匀分布）
分类准确率（label=female）：30–65%（高度不确定，视个体差异）
主要用途：量化 Engine A 在过渡区的不确定性范围，验证 advice "处于过渡区" 措辞触发阈值
```
