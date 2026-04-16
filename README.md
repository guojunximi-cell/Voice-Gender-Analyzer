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





## Railway 一键部署

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/<TEMPLATE_ID>)

点击上方按钮，Railway 会按 `railway.json` 蓝图自动创建两个服务：应用本体（从本仓库 Dockerfile 构建）和 Redis 插件，并把 `REDIS_URL` 注入到应用。首次构建约 10–15 分钟（TensorFlow + inaSpeechSegmenter 模型较大），完成后点击 Railway 分配的 Public URL 即可使用。

> 首次部署完成后，作者需要在 Railway 控制台 "Save as Template" 生成 Template ID，替换按钮 URL 里的 `<TEMPLATE_ID>` 占位符，之后社区访客就能真正一键复用。

### 手动部署（若按钮不可用）

1. Railway → New Project → Deploy from GitHub repo → 选本仓库
2. + Add Service → Database → Redis
3. 在 app 服务的 Variables 面板加 `REDIS_URL = ${{Redis.REDIS_URL}}`
4. 等构建完成，访问 Public URL

### 运行建议

- **推荐 Plan**：Hobby ($5/月)，内存 ≥ 512 MB。TensorFlow + 双进程（API + worker）在更低档可能 OOM
- **可选环境变量**：`LOG_LEVEL` (默认 WARNING)、`MAX_FILE_SIZE_MB` (默认 10)、`MAX_AUDIO_DURATION_SEC` (默认 180)、`MAX_CONCURRENT` (默认 2)、`MAX_QUEUE_DEPTH` (默认 30)

## 声明

本工具仅用于学术研究与语音技术学习目的。性别分析结果基于统计声学模型，不代表对个体性别的判断。

