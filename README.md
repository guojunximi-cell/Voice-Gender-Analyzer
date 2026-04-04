# 声音分析鸭 — 声音性别分析工具

基于深度学习与声学特征分析的音频性别识别 Web 应用。

## 致谢

本项目使用了以下开源成果：

* [inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter) — Doukhan et al., ICASSP 2018，MIT License
* [WaveSurfer.js](https://wavesurfer.xyz/) — 音频波形可视化

## 项目简介

声音分析鸭 是一款浏览器端音频分析工具，能够：

* 将音频文件压缩后分段
* 识别每段的性别标签（男声 / 女声 / 其他）的置信度
* 提取声学特征：基频/共振峰/共鸣
* 计算综合性别表达评分 (-100% to 100%)
* 在交互式散点图中记录历史分析会话

## 技术架构

|层次|技术|
|-|-|
|前端|Vanilla JS + Vite + WaveSurfer.js|
|后端|Python · FastAPI · Uvicorn|
|引擎|inaSpeechSegmenter|



## 运行

建议使用 \*\*Python 3.11\*\* 或 \*\*3.12\*\*。

需要安装 \[Node.js](https://nodejs.org/) (用于前端环境)。



``` powershell



pip install -r requirements.txt

cd frontend

npm install

python run\_app.py



```





## 声明

本工具仅用于学术研究与语音技术学习目的。性别分析结果基于统计声学模型，不代表对个体性别的判断。

