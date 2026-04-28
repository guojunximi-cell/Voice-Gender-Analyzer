# trans_masc

FTM（Female-to-Male）跨性别者，含训练早期（HRT前）至成熟期。

## 定义与 F0 范围

FTM 声音变化主要由睾酮（HRT）驱动，F0 下降幅度通常比 MTF 声音上移更快且更彻底。
训练阶段对此类别影响相对较小（HRT 是主要驱动因素）。

| 阶段 | F0 中位数 | F0 范围 | 备注 |
|------|-----------|---------|------|
| HRT 前 | 185–245 Hz | 160–290 Hz | 生理女性基线 |
| HRT 3–12 月 | 130–180 Hz | 100–220 Hz | 快速下降中，分布极宽 |
| HRT 1 年+ | 90–145 Hz | 75–175 Hz | 基本稳定，接近顺性别男性 |

**关键特征**：
- HRT 后 F0 快速进入男性范围（通常 6–12 个月内）
- 但 VTL / 共振峰保持生理女性值（声道较短），导致 F2 仍偏高
- Engine A 对成熟 FTM 声音预期标为 male（F0 驱动），但置信度可能低于 cis_male（F2 偏差）
- HRT 过渡期声音：Engine A 行为难以预测，是验证模型鲁棒性的有趣测试集

## 推荐公开数据源

### 注意事项

FTM 公开数据集比 MTF 更稀缺。HRT 前/中/后分期标注的数据几乎不存在。

### 学术数据集

| 来源 | 内容 | 获取方式 |
|------|------|---------|
| **TGVC** | 若含 FTM 子集 | https://github.com/TransVoiceLab（如已公开） |
| **Leung 等（2018）** | "Acoustic and perceptual evaluation of voice quality in FtM" | 联系论文作者 |

### 社区来源（公开许可）

- **YouTube**：FTM HRT 进度视频（"testosterone voice change", "T voice timeline"）
  - 部分创作者明确声明 CC0 或"随意使用"
  - 关键词：`ftm voice month 1/3/6/12`, `testosterone voice change timeline`
- **r/ftm** subreddit 的 "voice update" 帖（需原帖作者明确许可）

### 筛选方法

按 HRT 时长分为三个子组，manifest 中用 `notes` 字段记录：
- `hrt_none`：HRT 前
- `hrt_early`：HRT 0–12 个月
- `hrt_stable`：HRT 12 个月以上

## 录音质量要求

与 `cis_female/README.md` 相同。额外字段（manifest.yaml 中）：

- `notes` 字段记录：HRT 开始时间或时长（如已知）、是否使用额外嗓音训练

## 期望测试结果

```
HRT 前：
  C1-T2.0 margin：mean 0.72–0.88
  分类准确率（label=female）：85–95%（F0 高，Engine A 倾向 female）

HRT 12月+：
  C1-T2.0 margin：mean 0.60–0.82
  分类准确率（label=male）：70–90%（F0 已男性化，但 F2 偏差导致置信度低于 cis_male）

主要用途：量化 Engine A 对 F0 与 VTL 不一致声音的处理策略；与 cis_male_high_f0 形成对比
```
