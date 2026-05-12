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

`acousticgender/library/*.py` 在 vendor 之上加了 voiceya 自己的法语 / 韩语
分支（grep `voiceya patch` 可以找到全部锚点）。每次 rsync 升级 upstream 后，
必须把以下 diff 重新打回：

| 文件 | 行（升级前位置） | 改动 |
|------|------------------|------|
| `preprocessing.py` | L87 `mfa_model = ...` | 改成 4-way map：`{'zh':'mandarin_mfa','fr':'french_mfa','ko':'korean_mfa'}.get(lang,'english_mfa')` |
| `phones.py` | L25-44 `pronunciation_dict` 装载块 | 加 `elif lang == 'fr'` / `elif lang == 'ko'` 分支，对应 `french_mfa_dict.txt` / `korean_mfa_dict.txt` UTF-8；`if lang == 'zh':` 解析判断扩成 `lang in ('zh', 'fr', 'ko')`；`word_key` 的 upper 例外同步扩 fr + ko |
| `phones.py` | L17 `if line == "Phonemes:": ...` 之后 | 加 section-boundary 短路：识别任意以 `:` 结尾且不含 tab 的 header 视为新 section，把 `active_list` 置 None。`textgrid-formants.praat` 多 ceiling 版会追加 `Multi-Ceiling-Formants:` section，没这块兜底 phones.parse 会把多 ceiling 行也当 phoneme 解析→ IndexError |
| `resonance.py` | `ZH_VOWELS` 旁 / `stats_file` / `isVowel` | 加 `FR_VOWELS = {a,ɑ,e,ɛ,i,o,ɔ,u,y,ø,œ,ə,ɛ̃,ɑ̃,ɔ̃,œ̃}` + `KO_VOWELS = {ɐ, e, eː, ɛ, ɛː, i, iː, o, oː, u, uː, ɨ, ɨː, ʌ, ʌː}`（7 base × 短/长 + ɐ，15 个 IPA label）；`stats_file` 改 4-way map；`isVowel` 加 `elif lang == 'fr'` + `elif lang == 'ko'` 直查对应 vowel set |
| `textgrid-formants.praat` | 整脚本 | 单 ceiling 5000 Hz → 多 ceiling sweep（4500 / 5000 / 5500 / 6000 / 6500 Hz），原 `Phonemes:` section 保留以兼容老 wrapper（5000 Hz baseline），追加 `Multi-Ceiling-Formants:` section 给 `wrapper/ceiling_selector.py` 挑最优 ceiling 用。详见脚本头部注释 |

`wrapper/ceiling_selector.py` 不属于 vendor — 它在 wrapper 层消费 `Multi-Ceiling-Formants:` section，按"同元音类内 F1/F2/F3 变异最小"挑 ceiling，重写 `Phonemes:` section 后给 `phones.parse` 喂回。`multichunk.process_from_wav` 与 `main.py` 单 chunk 路径都接进去了，输出多一个 `formant_ceiling_hz` 字段供 worker 透传。回归测试在 `tests/test_french_ceiling_selector.py`（含 4 男 + 4 女 fr CommonVoice fixture）。

**语言门控**：`_ADAPTIVE_LANGS = {"fr", "zh"}`。两个共同特点：女声 /i / y / e/ 的 F2 在 5000 Hz ceiling 下会被 LPC 错误地折叠到 1500-1900 Hz（真实值 2200-2700 Hz），把女声共振峰 z-score 系统性压成"男向"。fr 是 voiceya 自训 baseline；zh 在 2026-05-01 用 AISHELL-3 train（5000 段，scripts/train_stats_zh.py）重训了 5500 Hz baseline 的 stats_zh.json（53 个 phoneme），把 /i/ F2 mean 从 1843 → 2264 Hz 拉回到接近文献值。en 暂时还在门外——`stats.json` 仍是 5000 Hz baseline，要等同样的重训才能开。门控之外只是 selector 本身的判断—— Praat 多 ceiling sweep 跑全语言（开销 +0.2 s/clip，可忽略），phones.py section-boundary 短路也是全语言生效，因为产物里始终有 `Multi-Ceiling-Formants:` section 等着被跳过。

法语资源（与中英文并列堆 `visualizer-backend/`）：
- `stats_fr.json`：voiceya 自训 baseline，由 `scripts/train_stats_fr.py` 跑
  Common Voice fr v17 的 ~10k 段产出，schema 与 `stats.json` 一致。
- `weights_fr.json`：抄 ZH v0.2.1 `[0.762, 0.236, 0.002]`，不单独训。EN `[0.732, 0.268, 0.0]` 与 ZH v0.2.1 在 spk-disjoint holdout 上验证过 F1+F2 主导的物理关系跨语言一致。重训必须 `--weights-spk-cv --weights-min-f2 0.20`（utt-level CV 会把 F2 砍掉、spk-CV 但 floor 太松又会偏向 F1-only，都是坑）。
- `french_mfa_dict.txt`：`mfa model download dictionary french_mfa` 后从
  `~/Documents/MFA/pretrained_models/dictionary/` 拷出来。

韩语资源（同样并列堆 `visualizer-backend/`）：
- `stats_ko.json`：voiceya 自训 baseline，由 `scripts/train_stats_ko.py` 跑
  Zeroth-Korean（OpenSLR SLR40，~51 hr，105 spk，CC BY 4.0，免 auth）的
  ~10k 段产出。schema 与 `stats.json` / `stats_fr.json` 一致。
- `weights_ko.json`：抄 ZH v0.2.1 `[0.762, 0.236, 0.002]`，不单独训
  （同 fr 红线——utt-level CV 暴搜会把 F2 砍掉）。
- `korean_mfa_dict.txt`：`mfa model download dictionary korean_mfa` 后从
  `/opt/mfa_root/pretrained_models/dictionary/` 拷出来（21 009 条
  Hangul → IPA 多概率前缀），Dockerfile 构建时自动 `find` + `cp` 到 /app/.

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

### 韩语 baseline 训练（一次性，手动）

`stats_ko.json` 也是 voiceya 自己训的。Dockerfile 已经把 `korean_mfa`
声学模型 + 字典烤进镜像；缺 `stats_ko.json` 时 sidecar 不会把 `ko`
放进 `/healthz` 的 `languages`，worker 请求 ko-KR 会 503 → `engine_c
= null` 优雅降级。

#### 数据集

用 [Zeroth-Korean (OpenSLR SLR40)](https://www.openslr.org/40/)：
51.6 hr / 105 speaker / `m`/`f` 性别标签 / CC BY 4.0 / 免 auth 直链 10 GB。

```bash
mkdir -p /mnt/d/project_vocieduck/ablation/audio/ko
cd /mnt/d/project_vocieduck/ablation/audio/ko
wget -c https://openslr.trmal.net/resources/40/zeroth_korean.tar.gz
tar -xzf zeroth_korean.tar.gz
```

结构：
- `AUDIO_INFO` — pipe-separated `SPEAKERID|NAME|SEX|SCRIPTID|DATASET`
- `train_data_01/<script>/<spk>/<spk>_<script>.trans.txt` — utterance manifest
- 同目录 `<spk>_<script>_<utt>.flac` — 16 kHz mono FLAC
- 总 22 263 train + 457 test utterance，14k F / 8k M

或者用 Common Voice ko v25（需要 click-through 下载，gender 列在
`validated.tsv`），与 fr 同一套读取方式——`train_stats_ko.py
--corpus-format cv` 走该路径。

#### 训练流程

```bash
# 1) 起 sidecar（构建会下载 korean_mfa，首次约 +5 min、+500 MB）
docker compose --profile engine-c up -d --build

# 2) 挂语料进容器：docker-compose.override.yml 加 volumes:
#    - /mnt/d/project_vocieduck/ablation/audio/ko:/mnt/ko-corpus:ro
#    然后 docker compose up -d 重 recreate

# 3) 把训练脚本 cp 进去
docker cp scripts/train_stats_ko.py visualizer-backend:/tmp/

# 4) 跑训练（10k 段，4 worker，~3-4 h CPU）
docker exec -d voice-gender-analyzer-visualizer-backend-1 \
    python /tmp/train_stats_ko.py \
        --corpus-format zeroth \
        --corpus /mnt/ko-corpus \
        --out /app/stats_ko.json \
        --n-segments 10000 \
        --num-workers 4

# 跟进度
docker exec voice-gender-analyzer-visualizer-backend-1 tail -F /tmp/train_ko.log

# 5) 拿出 stats_ko.json 提交到 vendor 目录、重新打镜像
docker cp visualizer-backend:/app/stats_ko.json \
          voiceya/sidecars/visualizer-backend/stats_ko.json
docker compose --profile engine-c up -d --build
```

#### 冒烟测试

```bash
# 验证 sidecar 上线了 ko
curl http://localhost:8001/healthz
# 期望: {"ok": true, "languages": ["zh", "en", "fr", "ko"]}

# 端到端：ko-KR 跟读模式（最稳，绕开 ASR）
curl -F audio=@ko_sample.wav -F mode=script \
     -F script="안녕하세요 만나서 반갑습니다" \
     -F language=ko-KR \
     http://localhost:8080/analyze-voice
```

断言：`summary.engine_c.language == "ko-KR"`，`phones[]` 非空，
`alignment_confidence.low_quality == false`。

**训完后还要做**：手动把 `wrapper/ceiling_selector.py:_ADAPTIVE_LANGS`
加上 `"ko"`——`stats_ko.json` 已经按 5500 Hz Praat ceiling 训练完
（同 fr / zh），adaptive ceiling 与 stats 校准一致。在那之前 ko 走
legacy 5000 Hz path，避免 over-correction。

### 本地构建 & 冒烟测试

```bash
docker build -f voiceya/sidecars/visualizer-backend.Dockerfile -t voiceya-engine-c:dev .
docker run --rm -p 8001:8001 voiceya-engine-c:dev
curl http://localhost:8001/healthz
```
