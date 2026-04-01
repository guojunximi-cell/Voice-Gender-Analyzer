# VoiceScope — 声音性别分析工具

基于深度学习与声学特征分析的音频性别识别 Web 应用。

## 致谢

本项目使用了以下开源成果：

- [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter) — Doukhan et al., ICASSP 2018，MIT License
- [WaveSurfer.js](https://wavesurfer.xyz/) — 音频波形可视化

## 项目简介

VoiceScope 是一款浏览器端音频分析工具，能够：

- 将音频文件压缩后分段
- 识别每段的性别标签（男声 / 女声 / 其他）的置信度
- 提取声学特征：基频/共振峰/共鸣
- 计算综合性别表达评分 (-100% to 100%)
- 在交互式散点图中记录历史分析会话

## 技术架构

| 层次 | 技术 |
|------|------|
| 前端 | Vanilla JS + Vite + WaveSurfer.js |
| 后端 | Python · FastAPI · Uvicorn |
| 引擎 | inaSpeechSegmenter |
| 预训练模型 | `interspeech2023_cvfr.hdf5` |

## 目录结构

```
├── 📄 核心文件
│   ├── acoustic_analyzer.py      # 声学分析器主模块
│   ├── main.py                   # 程序入口
│   ├── interspeech2023_cvfr.hdf5 # 模型权重文件
│   ├── Dockerfile
│   ├── railway.toml              # Railway 部署配置
│   ├── README.md
│   ├── requirements.txt
│   ├── requirements-prod.txt
│   └── .gitignore
│
├── 📁 frontend/                  # 前端 (Vite + wavesurfer.js)
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js
│   ├── src/
│   │   ├── modules/
│   │   ├── styles/
│   │   ├── main.js
│   │   └── utils.js
│   └── node_modules/
│
├── 📁 inaSpeechSegmenter-interspeech23/   # 语音分割子项目
│   ├── inaSpeechSegmenter/       # Python 包源码
│   ├── media/                    # 测试媒体文件
│   ├── scripts/
│   ├── tutorials/
│   ├── .github/workflows/
│   ├── setup.py
│   ├── Dockerfile
│   ├── LICENSE
│   └── README.md
│
├── 📁 scripts/                   # 脚本目录
├── 📁 output/                    # 输出目录
│   └── .gitkeep


## 测试和部署环境的更改 (loacation: main.py)

`ALLOW_CONCURRENT_PROCESSING = True` # 同时处理多文件 + max 200M
`ALLOW_CONCURRENT_PROCESSING = False` # 1 by 1 + max 5M

## 运行

```bash
# 终端 1：启动后端
# 首次运行会自动下载 inaSpeechSegmenter 的 CNN 模型（约 50MB）
python main.py

# 终端 2：启动前端开发服务器
cd frontend
npm run dev
```
访问端口即可使用。

## 声明

本工具仅用于学术研究与语音技术学习目的。性别分析结果基于统计声学模型，不代表对个体性别的判断。
