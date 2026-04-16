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

需要 **Python 3.13**、[Node.js ≥ 20](https://nodejs.org/)（装 pnpm 用）、[uv](https://docs.astral.sh/uv/)、本地 Redis。

### 本地开发

```bash
uv sync                 # 按 uv.lock 装 Python 依赖到 .venv
pnpm install            # 前端依赖
python run_app.py       # 一键起 Redis + uvicorn + taskiq worker + vite
```

`run_app.py` 会同时拉起后端、worker 与 vite dev server，默认访问 http://localhost:5173。

### Docker 自建（VPS / 自托管）

需要 Docker 与 Docker Compose v2。

```bash
cp .env.example .env    # 按需改动，REDIS_URL 留空用 compose 内置 redis
docker compose up -d --build
```

服务默认监听 `http://localhost:8080`。首次构建约 10~15 分钟（TensorFlow + inaSpeechSegmenter 模型较大）。可配置的环境变量清单见 `.env.example`。

### Railway 部署

Railway 按 `railway.toml` 构建。按以下步骤手动配置：

1. Railway → **New Project** → **Deploy from GitHub repo** → 选本仓库
2. **+ Add Service** → **Database** → **Redis**
3. 在 app 服务的 **Variables** 面板加 `REDIS_URL = ${{Redis.REDIS_URL}}`
4. 等构建完成，访问 Public URL

> 推荐 Hobby Plan（内存 ≥ 512 MB）。TensorFlow + API + worker 双进程在更低档可能 OOM。

## 声明

本工具仅用于学术研究与语音技术学习目的。性别分析结果基于统计声学模型，不代表对个体性别的判断。

