# voiceya/sidecars

进程外辅助服务的容器定义与封装代码。

## visualizer-backend（Engine C）

Vendored 自 [guojunximi-cell/gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization)
的 `working-chinese-version` 分支（commit 446f124, 2026-04-16 同步）。复用其经过
v0.1.1 修正的 MFA + Praat + `stats_zh.json` 验证链。

| 路径 | 作用 |
|------|------|
| `visualizer-backend/` | 上游项目的精简 vendor（只保留中文链路需要的文件） |
| `visualizer-backend.Dockerfile` | sidecar 镜像构建文件 |
| `wrapper/main.py` | FastAPI 薄壳 — 暴露 `/engine_c/analyze` 与 `/healthz` |

### 上游升级

每次想拉上游新版本时：

```bash
cd /path/to/gender-voice-visualization && git pull
rsync -a --delete \
  --exclude='.git' --exclude='__pycache__' --exclude='cmudict.txt' \
  --exclude='resources/' --exclude='ui/' --exclude='tools/' \
  --exclude='*.html' --exclude='sw.js' --exclude='manifest.json' \
  --exclude='backend.cgi' --exclude='build.cgi' --exclude='serve.py' \
  --exclude='settings.json' --exclude='railway.json' --exclude='Dockerfile' \
  --exclude='align.sh' --exclude='intro.md' --exclude='.dockerignore' \
  --exclude='.gitignore' \
  /path/to/gender-voice-visualization/ \
  voiceya/sidecars/visualizer-backend/
```

然后跑 `task 7` 验证套件。

### 本地构建 & 冒烟测试

```bash
docker build -f voiceya/sidecars/visualizer-backend.Dockerfile -t voiceya-engine-c:dev .
docker run --rm -p 8001:8001 voiceya-engine-c:dev
curl http://localhost:8001/healthz
```
