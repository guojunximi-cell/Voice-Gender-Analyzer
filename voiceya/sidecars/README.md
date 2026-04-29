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

### Vendor patches（必须在 rsync 后手动 reapply）

`acousticgender/library/*.py` 在 vendor 之上加了 voiceya 自己的法语分支
（grep `voiceya patch` 可以找到全部锚点）。每次 rsync 升级 upstream 后，
必须把以下 3 处 diff 重新打回：

| 文件 | 行（升级前位置） | 改动 |
|------|------------------|------|
| `preprocessing.py` | L87 `mfa_model = ...` | 改成 3-way map：`{'zh':'mandarin_mfa','fr':'french_mfa'}.get(lang,'english_mfa')` |
| `phones.py` | L25-44 `pronunciation_dict` 装载块 | 加 `elif lang == 'fr'` 分支，`french_mfa_dict.txt` UTF-8；`if lang == 'zh':` 解析判断扩成 `lang in ('zh', 'fr')`；`word_key` 的 upper 例外同步扩 fr |
| `resonance.py` | L14-16 `ZH_VOWELS` 旁 / L43 `stats_file` / L66 `isVowel` | 加 `FR_VOWELS = {a,ɑ,e,ɛ,i,o,ɔ,u,y,ø,œ,ə,ɛ̃,ɑ̃,ɔ̃,œ̃}`；`stats_file` 改 3-way map；`isVowel` 加 `elif lang == 'fr'` 直查 FR_VOWELS |

法语资源（与中英文并列堆 `visualizer-backend/`）：
- `stats_fr.json`：voiceya 自训 baseline，由 `scripts/train_stats_fr.py` 跑
  Common Voice fr v17 的 ~10k 段产出，schema 与 `stats.json` 一致。
- `weights_fr.json`：抄 ZH v0.2.1 `[0.762, 0.236, 0.002]`，不单独训。EN `[0.732, 0.268, 0.0]` 与 ZH v0.2.1 在 spk-disjoint holdout 上验证过 F1+F2 主导的物理关系跨语言一致。重训必须 `--weights-spk-cv --weights-min-f2 0.20`（utt-level CV 会把 F2 砍掉、spk-CV 但 floor 太松又会偏向 F1-only，都是坑）。
- `french_mfa_dict.txt`：`mfa model download dictionary french_mfa` 后从
  `~/Documents/MFA/pretrained_models/dictionary/` 拷出来。

### 法语 baseline 训练（一次性，手动）

`stats_fr.json` 是 voiceya 自己训的，不在仓库里。Dockerfile 已经把
`french_mfa` 声学模型 + 字典烤进镜像；缺 `stats_fr.json` 时 sidecar
不会把 `fr` 放进 `/healthz` 的 `languages`，worker 请求 fr-FR 会优雅
降级到 `summary.engine_c = null`。

#### 数据集

下载 [Common Voice fr v17](https://commonvoice.mozilla.org/zh-CN/datasets)
（fr 子集，~15 GB 解压），目录结构是 `cv-corpus-17.0-XXXX/fr/{clips/,validated.tsv,...}`。

#### 训练流程

脚本必须**进 sidecar 容器跑**——不走 HTTP，直接调 vendored library。
没 stats_fr.json 时 `resonance.compute_resonance` 会在
`statistics.mean([])` 上炸；脚本绕开它，只用
`preprocessing.process` + `phones.parse` 拿原始 F-vectors。

```bash
# 1) 起 sidecar（构建会下载 french_mfa，首次约 +5 min、+500 MB）
docker compose --profile engine-c up -d --build

# 2) 把 CV fr 语料挂进容器（host 路径 → /mnt/cv-fr）
docker cp ~/datasets/cv-corpus-17.0-XXXX visualizer-backend:/mnt/cv-fr
# 或者：在 docker-compose.yml 给 visualizer-backend 加 volumes:
#   - ~/datasets/cv-corpus-17.0-XXXX:/mnt/cv-fr:ro

# 3) 把训练脚本 cp 进去
docker cp scripts/train_stats_fr.py visualizer-backend:/tmp/

# 4) 跑训练（10k 段，~5 h CPU；checkpoint 保留在 /tmp，可断点续跑）
docker exec -it visualizer-backend python /tmp/train_stats_fr.py \
    --corpus /mnt/cv-fr/cv-corpus-17.0-XXXX/fr \
    --out /app/stats_fr.json \
    --n-segments 10000

# 5) 拿出 stats_fr.json 提交到 vendor 目录、重新打镜像
docker cp visualizer-backend:/app/stats_fr.json \
          voiceya/sidecars/visualizer-backend/stats_fr.json
docker compose --profile engine-c up -d --build
```

#### 冒烟测试

```bash
# 验证 sidecar 上线了 fr
curl http://localhost:8001/healthz
# 期望: {"ok": true, "languages": ["zh", "en", "fr"]}

# 端到端：fr-FR 跟读模式（最稳，绕开 ASR）
curl -F audio=@fr_sample.wav -F mode=script \
     -F script="bonjour je voudrais commander un café" \
     -F language=fr-FR \
     http://localhost:8080/analyze-voice
# 然后 GET /status/<task_id> with Accept: text/event-stream
```

断言：`summary.engine_c.language == "fr-FR"`，`phones[]` 非空，
`alignment_confidence.low_quality == false`。

### 本地构建 & 冒烟测试

```bash
docker build -f voiceya/sidecars/visualizer-backend.Dockerfile -t voiceya-engine-c:dev .
docker run --rm -p 8001:8001 voiceya-engine-c:dev
curl http://localhost:8001/healthz
```
