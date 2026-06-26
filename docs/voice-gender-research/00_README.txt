Voice-Gender-Analyzer 研究成果包
================================
主题：trans/cis 声音性别特征 · NN/LLM pass(通过)检测 · 循证嗓音训练方法
产出日期：2026-06-26
方法：14 维度并行文献检索 + 3 份评审 critic + 10 项对抗性核验

文件清单
--------
00_README.txt                         本说明
01_文献综述与工程路线图.md             ★主文档：第一部分文献综述(带引用)/第二部分综合+资源排序/第三部分落到本项目的分阶段工程方案
02_对抗性核验_10项.md                  解决初稿冲突数字+补关键缺口(cis F0常模、模糊带、Gelfer系列、睾酮、中文声调、共振特征、strain、VFP、on-device、弃权校准)
03_全维度详digest_含每条来源与资源.txt   声学+感知两维度的完整发现/量化事实/资源(每条带来源URL)
04_精简digest_其余12维度.txt           MTF/FTM/ML/开源/测量/SLP/LLM/书目/伦理/数据集/非二元/语音转换 的发现+资源(带许可)
05_原始结构化数据_research_extract.json 全部 survey(14维度)+critics(3) 的原始结构化 JSON(每发现含 claim/detail/source/confidence)

一句话结论
----------
本项目已用的 inaSpeechSegmenter(MIT) 官方内置 VoiceFemininityScoring，即 Doukhan《Voice Passing》(Interspeech 2023)
把二元性别分数 isotonic 校准到听者感知的连续女性度，跨性别说话人 R²≈0.94——pass/uncertain/no-pass 的近乎零成本引擎。
绝不做纯音高检测器：F0+共振峰共同决定感知，模糊带 ~150-165 Hz，带内共振峰约 19-20% 推翻音高。
