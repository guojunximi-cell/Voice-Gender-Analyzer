# VoiceScope — 声音性别分析工具

基于深度学习与声学特征分析的音频性别识别 Web 应用。

## 项目简介

VoiceScope 是一款浏览器端音频分析工具，能够：

- 将音频文件分段并识别每段的性别标签（男声 / 女声 / 其他）
- 提取声学特征：基频（F0）、共振峰（F1/F2/F3）、频谱倾斜、声道长度
- 计算综合性别表达评分（0 = 男性化，100 = 女性化）
- 在交互式散点图中记录历史分析会话

## 技术架构

| 层次 | 技术 |
|------|------|
| 前端 | Vanilla JS + Vite + WaveSurfer.js |
| 后端 | Python · FastAPI · Uvicorn |
| 引擎 A（分段分类） | inaSpeechSegmenter（Doukhan et al., ICASSP 2018） |
| 引擎 B（声学分析） | librosa · SciPy LPC · pyin 基频追踪 |
| 预训练模型 | `interspeech2023_cvfr.hdf5`（TensorFlow/Keras） |

## 目录结构

```
├── main.py                              # FastAPI 后端服务
├── acoustic_analyzer.py                 # 声学特征分析引擎（Engine B）
├── interspeech2023_cvfr.hdf5            # 预训练 Keras 模型
├── requirements.txt                     # Python 直接依赖
├── scripts/
│   ├── predict.py                       # 模型推理探索脚本（进行中）
│   └── test.py                          # 模型加载验证脚本
├── frontend/                            # Vite 前端
│   ├── index.html
│   ├── package.json
│   └── src/
│       ├── main.js
│       ├── utils.js
│       ├── modules/                     # 功能模块
│       └── styles/
├── inaSpeechSegmenter-interspeech23/    # 本地 vendored 依赖
└── output/                              # 分析结果输出目录
```

## 快速开始

### 环境要求

- Python 3.11
- Node.js 18+
- ffmpeg（inaSpeechSegmenter 的音频解码依赖）

### 安装

```bash
# 1. 安装 Python 依赖
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. 安装本地 vendored 库
pip install -e ./inaSpeechSegmenter-interspeech23

# 3. 安装前端依赖
cd frontend
npm install
```

### 运行

```bash
# 终端 1：启动后端
# 首次运行会自动下载 inaSpeechSegmenter 的 CNN 模型（约 50MB）
python main.py

# 终端 2：启动前端开发服务器
cd frontend
npm run dev
```

访问 [http://localhost:5173](http://localhost:5173) 即可使用。

## 声学特征说明

| 特征 | 描述 |
|------|------|
| F0（基频） | 语音的音高，单位 Hz。女性通常 175–255 Hz，男性 85–155 Hz |
| F1/F2/F3（共振峰） | 声道谐振频率，通过 LPC 分析提取 |
| 频谱倾斜 | 低频与高频能量之比（dB/倍频程），负值越大越偏男性化 |
| 共鸣评分 | 基于 F3 估算声道长度后映射到 0–100% |
| 综合性别评分 | 加权融合：音高 45% + 共振峰 30% + 共鸣 15% + 频谱倾斜 10% |

## 致谢

本项目使用了以下开源成果：

- [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter) — Doukhan et al., ICASSP 2018，MIT License
- [WaveSurfer.js](https://wavesurfer.xyz/) — 音频波形可视化

## 声明

本工具仅用于学术研究与语音技术学习目的。性别分析结果基于统计声学模型，不代表对个体性别的判断。
