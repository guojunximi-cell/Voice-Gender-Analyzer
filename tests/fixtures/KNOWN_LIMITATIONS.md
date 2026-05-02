# 测试样本已知局限性

> **目的**：避免将合成样本的统计当作证据。架构决策、阈值标定、Engine C 信号设计
> 必须基于真实样本；合成样本只能用于趋势观察。

## 合成样本的技术原理

`tests/fixtures/audio/{trans_fem_*,trans_masc,neutral,cis_male_high_f0/synth_*}` 中
所有 `synth_*.wav` 文件均由 `sox <input> <output> pitch <CENTS>` 生成。

**关键事实**：sox 的 `pitch` 命令是 **WSOLA 时间-频率全局缩放**，不是声码器分离。
它同时移动 F0 和共振峰，不保留共振峰位置。

```
sox bdl_a0001.wav out.wav pitch 500   # +5 半音
↓ 实际效果：
F0:  131 Hz → 174 Hz   (×1.34)
F1:  ~760 Hz → ~1018 Hz (×1.34，同步上移)
F2:  ~1100 Hz → ~1473 Hz (×1.34)
F3:  ~2400 Hz → ~3216 Hz (×1.34)
```

这意味着合成样本本质是"全频谱缩放后的语音"，对 Engine A 而言：
- 上移合成（trans_fem 系列）：声学指纹接近真实女声 → Engine A 可能正确分类为 female
- 下移合成（trans_masc）：声学指纹接近真实男声 → Engine A 可能正确分类为 male

## 可以用合成样本做什么

| 用途 | 是否可用 | 原因 |
|------|---------|------|
| trans_fem 系列的 margin 趋势观察（HRT 进度对应越高 F0，margin 应越高） | ✓ | 仅观察单调性，不依赖绝对值 |
| 验证 test_confidence_c1.py 脚本本身工作正常 | ✓ | 数据存在性测试 |
| 给 Engine A 喂多样化输入做冒烟测试 | ✓ | 任意波形即可 |
| 验证 manifest.yaml 加载逻辑 | ✓ | 数据流测试 |

## **不可以**用合成样本做什么

| 用途 | 是否可用 | 原因 |
|------|---------|------|
| 架构决策（advice 系统的 reject 区间设计） | ✗ | 阈值会被合成样本的非真实分布带偏 |
| 阈值标定（`certainty.boundary` 触发条件） | ✗ | 合成样本的 margin 分布与真实声音不一致 |
| Engine C 信号设计（VTL 估计、共振峰评分） | ✗ | 共振峰被全局缩放，不反映真实跨性别声音的解耦特征 |
| 验证 cis_male_high_f0 的 F0/共振峰解耦 bias | ✗ | 合成样本的共振峰也被上移，无法测试解耦 |
| 论文/报告中的统计声明 | ✗ | 合成数据不构成实验证据 |

## 必须获取的真实样本

### cis_male_high_f0（最高优先级，仍有缺口）

**当前状态**（2026-04-27）：仍只有 2 个真实样本。

**已尝试**：
- 下载 VCTK 0.92 完整 zip（11 GB）— 服务器不支持 Range，单次连接最多取得 1.4 GB
  （p225-p248 文本 + 14 个说话人的部分音频），未触及目标 speaker p254/p274/p286
- HuggingFace VCTK 镜像 `Jungjee/VCTK`、`vrgz2022/VCTK_092` — 401 私有
- HuggingFace `CSTR-Edinburgh/vctk` — 仅有加载脚本，实际仍走 Edinburgh 源
- Internet Archive `vctk-0.92` — 503 不可达

**已扩充**（部分缓解，但未填补真正缺口）：
- 14 个 VCTK speaker 的前 3 个句子已纳入 `cis_female`（10 speaker）和 `cis_male_standard`（4 speaker）
- 这批 VCTK 男声（p302/p304/p334/p360）F0 均在 88-115 Hz，**全部是标准男声**，对 high_f0 类别无帮助

**目标**：扩到 10-20 个真实样本，至少 5 个 speaker。

**下次尝试方案**：
1. 单独从 ftp/wget 下载 VCTK 完整 zip（用 `wget -c` + 长 timeout，可分多次断点续传）
2. 或申请 VCTK speaker subset 直接下载（联系 CSTR Edinburgh）
3. 或使用 LibriTTS test-clean.tar.gz（1.2 GB，OpenSLR 支持 Range，可分块下）筛选 F0 > 145 Hz 男声
4. 或使用 AISHELL-3 中文男声（F0 普遍偏高）— 仅 sample 子集足以

**推荐来源**：
1. **VCTK 0.92**（CC-BY 4.0）— 标注 F0 的男声 speaker：
   - p254（English SSE，F0~155Hz）、p274（F0~162Hz）、p286（F0~158Hz）、p255（F0~150Hz）
   - 每个 speaker 取 3-5 句 Rainbow Passage 或常用提示句
2. **LibriTTS**（CC-BY 4.0）— 男声 speaker 的 F0 元数据可在 SPEAKERS.txt 中筛选
3. **Mozilla Common Voice** — F0 需自测；优先 zh-CN / ja 因东亚男性 F0 整体偏高
4. **AISHELL-3**（CC-BY 4.0）— 中文男性 speaker，F0 实测筛选 > 145Hz 的样本

### trans 系列（中等优先级）

**当前状态**：0 个真实样本，全部合成。

**目标**：每个子类别至少 3-5 个真实样本，标注 HRT/训练阶段。

**推荐来源**（需考虑伦理与授权）：
- TGVC（如已公开）
- r/transvoice "progress check"（必须取得原帖作者书面许可）
- YouTube 嗓音训练频道（仅使用明确 CC 许可的内容）

详见各类别目录下 README.md 的"推荐公开数据源"章节。

### neutral（低优先级）

**当前状态**：3 个合成样本，但 sox pitch shift 不能产生真正声学中性的声音
（共振峰仍被同步移动）。

**目标**：从 VCTK / LibriTTS 中筛选低 F0 女性（160-180Hz）+ 高 F0 男性（145-165Hz），
组成真实声学中性边界样本。

## 在 manifest.yaml 中的标记规范

每个合成样本的 `notes` 字段必须包含：
- `synthetic_pitch_shift` 标识符
- 原始 speaker 与移调量（cents）
- 该样本的局限性说明（如 cis_male_high_f0 合成样本的 notes）

`source` 字段：合成样本写原始 speaker 来源（如 `CMU_ARCTIC_BDL`），不写 `synthetic`。
通过 notes 区分真实/合成。

## 再处理时机

获取真实 VCTK 样本后：
1. 删除 `cis_male_high_f0/synth_*.wav`（误导性强）
2. 保留 `trans_*` 和 `neutral` 合成样本，但在 manifest 顶部加注释明确标注
3. 重跑 `tests/test_confidence_c1.py`，记录真实样本的 margin 分布作为 advice 系统标定基准
