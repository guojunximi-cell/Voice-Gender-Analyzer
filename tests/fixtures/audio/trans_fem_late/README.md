# trans_fem_late

MTF（Male-to-Female）跨性别者嗓音训练后期 / 训练成熟阶段。

## 定义与 F0 范围

训练 18 个月以上，声音已基本稳定在女性感知范围，或被多数听众感知为女声。

| 指标 | 典型值 |
|------|--------|
| F0 中位数 | 185–240 Hz |
| F0 范围 | 160–280 Hz |
| 声道长度（VTL） | 15–17 cm（共振峰训练效果已稳定） |
| 共振峰 F2 | 1700–2100 Hz（接近顺性别女性均值） |

**关键特征**：
- F0 已稳定进入女性范围
- 共振峰经过长期训练已部分上移（VTL 感知缩短）
- 语音生理结构仍为男性声带（更长、更厚），但声学特征向女性区间收敛
- Engine A 预期大多标为 female，置信度应较高
- **是验证模型能否识别"声学上女性化但生理结构异常"的关键类别**

## 推荐公开数据源

### 注意事项

训练成熟的跨性别声音与顺性别女声在声学上高度重叠，数据标注时需明确说话人身份而非纯声学判断。

### 学术数据集

| 来源 | 内容 | 获取方式 |
|------|------|---------|
| **TGVC** | 若含"trained"或"post-transition"子集 | https://github.com/TransVoiceLab（如已公开） |
| **VF（Voice Femininity）数据集** | 含专业评估的跨性别女声 | 联系 Yaniv 等（2019）论文作者 |

### 社区来源（公开许可）

- **YouTube**：声音训练师的展示视频（如 TransVoiceLessons 的学员展示），部分明确 CC 许可
- **播客/访谈**：部分跨性别女性公开发布的音频内容（需书面许可）

### 声学筛选标准

从任何来源取得的音频，用以下条件验证属于此类别：
```bash
python3 -c "
import librosa, numpy as np
y, sr = librosa.load('sample.wav', sr=None)
f0, _, _ = librosa.pyin(y, fmin=100, fmax=400, sr=sr)
print(f'F0 median: {np.nanmedian(f0):.0f} Hz')
print(f'Expected: 185-240 Hz for trans_fem_late')
"
```

## 录音质量要求

与 `cis_female/README.md` 相同。额外字段（manifest.yaml 中）：

- `notes` 字段记录：训练总时长（如已知）、是否进行过 VFS/声带手术（如已知）

## 期望测试结果

```
C1-T2.0 margin：mean 0.70–0.88（接近 cis_female，但分布略宽）
分类准确率（label=female）：75–95%（优于 trans_fem_mid，但低于 cis_female）
主要用途：验证 Engine A 能否正确识别训练成熟声音；与 cis_female 对比找出残余偏差
```
