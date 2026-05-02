# trans_fem_early

MTF（Male-to-Female）跨性别者嗓音训练早期。

## 定义与 F0 范围

训练开始 0–6 个月，或尚未系统训练的跨性别女性。声音特征接近训练前基线。

| 指标 | 典型值 |
|------|--------|
| F0 中位数 | 100–155 Hz |
| F0 范围 | 80–180 Hz |
| 声道长度（VTL） | 17–19 cm（青春期已定型） |
| 共振峰 F2 | 1100–1600 Hz |

**关键特征**：
- F0 通常仍在男性范围，或刚刚进入过渡区
- 共振峰较男性变化不大
- Engine A 预期大多标为 male，少数高音帧误标 female
- 此类别代表 **app 最重要的用户群体**：她们来这里是因为想知道自己的声音在哪里

## 推荐公开数据源

### 注意事项

跨性别者嗓音数据集极度稀缺，且涉及隐私。以下来源须在使用前确认授权和知情同意。

### 学术数据集

| 来源 | 内容 | 获取方式 |
|------|------|---------|
| **TIMIT-TG**（假设存在） | 如有跨性别子集，需联系原作者 | 通常需要机构申请 |
| **Yaniv 等（2019）** | "Voice-Based Automatic Detection of the Voice Femininity Degree" 附带小型数据集 | 联系论文作者 |
| **TGVC（Trans Gender Voice Corpus）** | 多国跨性别者语音，含训练进度标注 | https://github.com/TransVoiceLab （如已公开） |

### 社区来源（公开许可）

- **r/transvoice** subreddit：用户自愿分享训练录音，部分帖子明确声明 CC0 或"随意使用"
  - 关键词搜索："rate my voice"、"progress check"
  - 必须取得原帖作者明确书面许可
- **YouTube 嗓音训练频道**（声明 CC 许可证的）：
  - Zoey Alexandria、TransVoiceLessons、Acapela Voice Training 等频道的进度视频
  - 仅使用标注了 CC 许可证的视频，或直接联系创作者

### 合成近似（临时占位）

在真实数据获取前，可用以下方法合成近似样本：

```bash
# 对 cis_male_standard 说话人做基频上移 +20 Hz（pitch shift，不改变共振峰）
# 此为声学近似，不代表真实跨性别早期声音特征
sox input.wav output.wav pitch +300   # 约 +20 Hz
```

标注时 `notes` 字段注明 `synthetic_pitch_shift`，避免混入真实数据分析。

## 录音质量要求

与 `cis_female/README.md` 相同。额外字段（manifest.yaml 中）：

- `notes` 字段记录：HRT 月数（如已知）、是否正在接受训练课程、录音时间（可以只写年月）

## 期望测试结果

```
C1-T2.0 margin：mean 0.60–0.85（较宽分布）
分类准确率（label=male）：50–80%（因 F0 已部分进入过渡区）
主要用途：确立 advice 系统的"起始基线"参考区间
```
