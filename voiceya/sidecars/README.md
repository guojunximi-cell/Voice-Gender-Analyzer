# voiceya/sidecars

进程外辅助服务的容器定义与封装代码。

## visualizer-backend（Engine C）

Vendored 自 [guojunximi-cell/gender-voice-visualization](https://github.com/guojunximi-cell/gender-voice-visualization)
的 `working-chinese-version` 分支（commit 446f124, 2026-04-16 同步）。复用其经过
v0.1.1 修正的 MFA + Praat + `stats_zh.json` 验证链；在同一份 vendor 里并行跑
`stats.json` / `cmudict.txt` 实现英文分支（`acousticgender/library/*.py` 本身已写好
`lang='en'|'zh'` 分支逻辑，零改动复用）。

| 路径 | 作用 |
|------|------|
| `visualizer-backend/` | 上游项目的精简 vendor（中英双语资源） |
| `visualizer-backend/cmudict.txt` | ARPABET 发音词典，英文专用；从上游 `master` 分支单独补入（见下） |
| `visualizer-backend.Dockerfile` | sidecar 镜像构建文件（build 阶段下载 mandarin_mfa + english_mfa） |
| `wrapper/main.py` | FastAPI 薄壳 — 暴露 `/engine_c/analyze`（接收 `language` 表单字段）与 `/healthz` |

### 上游升级

每次想拉上游新版本时：

```bash
cd /path/to/gender-voice-visualization && git pull
rsync -a --delete \
  --exclude='.git' --exclude='__pycache__' \
  --exclude='resources/' --exclude='ui/' --exclude='tools/' \
  --exclude='*.html' --exclude='sw.js' --exclude='manifest.json' \
  --exclude='backend.cgi' --exclude='build.cgi' --exclude='serve.py' \
  --exclude='settings.json' --exclude='railway.json' --exclude='Dockerfile' \
  --exclude='align.sh' --exclude='intro.md' --exclude='.dockerignore' \
  --exclude='.gitignore' \
  /path/to/gender-voice-visualization/ \
  voiceya/sidecars/visualizer-backend/
```

> 注意：rsync 不再排除 `cmudict.txt`——它是英文管线的必需资源。若升级上游时
> master / chinese 两个分支文件集合不一致，优先保证 `stats_zh.json`、`stats.json`、
> `weights_zh.json`、`weights.json`、`mandarin_dict.txt`、`cmudict.txt` 六个文件都在位。

**cmudict.txt 的来源**：`working-chinese-version` 分支默认不带这个文件。第一次引入时
（2026-04-22）从 upstream master 分支手动复制：

```bash
cp /path/to/gender-voice-visualization/cmudict.txt \
   voiceya/sidecars/visualizer-backend/cmudict.txt
```

然后跑 `task 7` 验证套件。

### 本地构建 & 冒烟测试

```bash
docker build -f voiceya/sidecars/visualizer-backend.Dockerfile -t voiceya-engine-c:dev .
docker run --rm -p 8001:8001 voiceya-engine-c:dev
curl http://localhost:8001/healthz
```
