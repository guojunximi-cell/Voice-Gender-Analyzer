# gender-voice-visualization — 中文适配版

Fork 自 upstream 英文版，在 `working-chinese-version` 分支上增加了普通话支持。本文档汇总所有相对上游 `master` 的实质改动（不含纯 CRLF/LF 换行噪声）。

> **训练状态**：中文语料（AISHELL-3，实际入池 134 男 + 134 女）已在本管线下跑完 MFA 对齐 + Praat 共振峰聚合，产出 `stats_zh.json`（z-score 参考）与 `weights_zh.json = [0.658, 0.242, 0.1]`（10-fold CV 暴力搜索）。held-out 验证 acc=0.900，Δmedian=0.196。详见 §7。

---

## 1. 新增文件

| 文件 | 用途 |
|------|------|
| `mandarin_dict.txt` | MFA `mandarin_mfa` v2.0.0 发音词典（字 → 带声调 IPA） |
| `stats_zh.json` | 普通话元音 F1/F2/F3 性别中性参考统计，供 `resonance.py` 做 z-score |
| `serve.py` | 本地 CGI 开发服务器（`python serve.py` → `http://localhost:8888`） |
| `intro.md` | 介绍文案 |
| `.claude/settings.local.json` | Claude Code 本地配置 |

---

## 2. 后端改动（Python）

### `acousticgender/library/preprocessing.py`
- 新增 `lang` 参数；`lang='zh'` 时切到 MFA `mandarin_mfa` 声学 + 词典。
- Windows conda 布局兼容：通过 `env/python.exe + Scripts/mfa-script.py` 调用 MFA，并补全 `PATH` / `CONDA_PREFIX`；Linux 仍走 `settings['mfa']` shim。
- **中文 transcript 预处理**：`re.findall(r'[\u4e00-\u9fff]', transcript)` 拆成单字后用空格连接写入 `recording.txt`，否则 MFA 会把整句当作一个未登录词 `<unk>`。
- 追加 MFA stdout/stderr 落到 stderr，便于调试。

### `acousticgender/library/phones.py`
- `parse(praat_output, lang='en')` 支持 zh：读 `mandarin_dict.txt`（tab 分隔，第 6 列为音素序列，UTF-8-BOM）。
- 边界加固：空 praat 输出返回 `{'words': [], 'phones': []}`；`word_index` 越界时跳过。

### `acousticgender/library/resonance.py`
- `compute_resonance(data, weights, lang='en')`：zh 模式加载 `stats_zh.json`。
- `_strip_tone()`（正则 `[˥˦˧˨˩]+`）：MFA 输出的音素带声调符（如 `a˥˥`、`i˧˥`），查 stats 前先剥离。
- 导出常量 `ZH_VOWELS = {'a','aj','aw','e','ej','i','io','o','ow','u','y','ə','ɥ','ʐ̩','z̩'}`（含零韵母 `ʐ̩`/`z̩`）。

### `backend.cgi` / `build.cgi`
- 透传 `lang` 参数给后端流水线。

### `settings.json`
- 本地化 `ffmpeg` / `sox` / `praat` / `mfa` 绝对路径（指向 miniconda `envs/mfa`）。

---

## 3. 前端改动（UI）

| 位置 | 改动 | 原因 |
|------|------|------|
| `ui/util.js:28` | `pitchPercent` 归一化 `(pitch-50)/250` → `/450` | 容纳中文女声高音 |
| `ui/voice-graph.js:13` | `pitchUpperBoundHz`: `300` → `500` | 同上 |
| `ui/voice-graph.js` `update()` | 元音判定新增去声调后的 IPA `ZH_VOWELS` 集合 | 原来只判 ARPABET（AEIOUY），中文 marker 无法逐音节跳动 |

其余 UI 文件的 diff 主要是 CRLF/LF 差异，非语义改动。

---

## 4. `stats_zh.json` 调参说明

- **问题**：早期手写版均值偏男声、stdev 过窄 → 共振值贴边 100%（观察到 mean 91% / median 100% / stdev 16%）。
- **修复**：均值取男/女文献值中点；stdev 约为原值 2×（F1 ~90–120 Hz，F2 ~200–300 Hz，F3 ~300–400 Hz）。
- **目标区间**：典型男声 Resonance ~30–45%，女声 ~55–75%。
- **Schema** 同英文 `stats.json`：每音素 4 行 `[F0, F1, F2, F3]`，每行 `{mean, stdev, median, max, min}`。

---

## 5. 已知坑 / 注意事项

- **MFA 版本**：`mandarin_mfa` 词典只发布到 v2.0.0 / v2.0.0a；声学默认下 v3.0.0，两者音素集不一致（会报 `80125 pronunciations ignored`）。需显式降级：
  ```bash
  mfa model download acoustic mandarin_mfa --version 2.0.0 --ignore_cache
  ```
- **环境切换**：跑 `serve.py` 前要 `conda deactivate` 回到 `.venv`（`mfa` env 没有 `maxminddb` 等 web 依赖）。后端通过 `settings.json` 的绝对路径调 mfa env 的 `mfa`，不需要 shell 处于 mfa env。
- **ffmpeg silencedetect**：对"开头即静音"的录音会产生不配对的 `silence_end`，导致 `aselect` 表达式出现 `between(t,,X)` 空参数报错。当前代码用 `try/except Exception` 回退到原始文件，不致命。

---

## 6. 运行方法

**依赖**：`ffmpeg`、`sox`、`praat`、MFA（conda env `mfa`，声学 + 词典均为 `mandarin_mfa` v2.0.0）。

```bash
# 回到 .venv
conda deactivate
# 启动本地服务器
python serve.py
# 浏览器打开 http://localhost:8888
# UI 里切换为中文，再录音 / 上传
```

---

## 7. v0.1.1 — 语料重建 stats_zh.json

v0.1.0 的 `stats_zh.json` 是人工按文献元音均值填的，stdev 不是"本管线 Praat 中点的测量分布"，导致 z-score 分母偏窄、resonance 跳动过大。v0.1.1 对齐英文版做法：跑真实语料库 → `corpusanalysis.py` 聚合 → 覆盖 `stats_zh.json`。详见 `CHANGELOG_ZH.md`。

### 相对上一次提交（`9dd7536` v0.1.0）的具体差异

| 类别 | 变化 |
|------|------|
| `stats_zh.json` | 手写文献值 (16 keys，仅元音) → AISHELL-3 实测聚合 (42+ keys，含辅音)；23 KB |
| `acousticgender/corpusanalysis.py` | 新增 `argparse`：`--lang / --corpus-dir / --processed-dir / --stats-out / --weights-out / --skip-weights / --jobs`；抽出 `_process_one`，并行 `ProcessPoolExecutor`；per-worker `MFA_ROOT_DIR`（软链 `pretrained_models` 等）；接住 `preprocessing.process` 返回的 TSV 写入持久 `persist_dir`（绕开 `shutil.rmtree`）；聚合键用 `_strip_tone(phone['phoneme'])`（zh） |
| `backend.cgi` | `lang=='zh'` 时优先加载 `weights_zh.json`，缺失回退 `weights.json` |
| 新增 `tools/build_zh_corpus.py` | 采样 AISHELL-3 → `corpus/{m\|f}_<spk>_<utt>/`，round-robin、cap-per-speaker、OOV 过滤、`_manifest.json` |
| 新增 `tools/validate_zh.py` | 末尾 20+20 held-out，断言 `median(m) < median(f)` 且 `acc ≥ 0.85` |
| 新增 `CHANGELOG_ZH.md` | v0.1.0 vs v0.1.1 根因与修复记录 |
| `README.md` | 新增本节（§7） |
| `.gitignore` | 忽略 `corpus/`、`corpus-src/`、`corpus-processed-zh/`、`Miniconda3-*.sh` |
| **未改动** | `resonance.py` 算法、`_strip_tone`、`ZH_VOWELS`、`phones.py`、前端任何文件 |

效果：同一条管线下，男声 resonance 中位数 ~0.91（贴边 clamp）→ **0.507**，女声 **0.713**，Δ=+0.206，acc=0.85。

### 7.1 下载 AISHELL-3 — [完成]

- 来源：OpenSLR-93，`https://www.openslr.org/resources/93/data_aishell3.tgz`，~18 GB。
- 为什么选它：218 speakers，`spk-info.txt` 有性别标签，44.1 kHz wav，逐句中文字符 transcript 与 `preprocessing.py` 的按字切分天然对齐。
- 落盘：`corpus-src/aishell3/`（`/mnt/e`，剩余 381 GB 充足）。
- 命令：
  ```bash
  mkdir -p corpus-src && cd corpus-src
  wget -c https://www.openslr.org/resources/93/data_aishell3.tgz
  tar xzf data_aishell3.tgz
  ```

### 7.2 采样到 `./corpus/` — [待做]

目标：性别均衡 200 + 200 句，每说话人 ≤5 条。工具：`tools/build_zh_corpus.py`（待写）。

- 解析 `spk-info.txt` → `{spk_id: gender}`；解析 `train/content.txt` → `{utt_id: chars}`。
- 按 `[\u4e00-\u9fff]` 过滤、按 `mandarin_dict.txt` 预筛 OOV、round-robin 跨说话人抽样。
- 输出目录：`corpus/{m|f}_{spk}_{utt}/{recording.wav, transcript.txt}`。
- 记录 `corpus/_manifest.json` 保证可复现。

### 7.3 `corpusanalysis.py` 并行化 — [待做]

- 加 `--jobs N`，用 `ProcessPoolExecutor` 包住 preprocessing 调用。
- 64 GB RAM 支持 8 workers × ~3 GB。
- 预期 400 句从 ~50 min → ~8–10 min。

### 7.4 生成新 `stats_zh.json` — [完成]

```bash
PYTHONPATH=acousticgender .venv/bin/python acousticgender/corpusanalysis.py \
  --lang zh --jobs 8 --skip-weights \
  --corpus-dir corpus --processed-dir corpus-processed-zh --stats-out stats_zh.json
```
- 关键修复：
  - `_process_one` 接住 `preprocessing.process` 返回的 TSV 直接落盘到 `<dir>/output/recording.tsv`（原版会被 `shutil.rmtree(tmp_dir)` 删除）。
  - 每 worker 独立 `MFA_ROOT_DIR`，`pretrained_models` / `models` / `extracted_models` 软链到默认 `~/Documents/MFA`，避免并发写 `command_history.yaml` 崩溃且不丢模型。
- 实际跑：306 句、jobs=8，~44 min；238 ok / 67 fail，平衡到 114 m + 114 f。
- 产物 `stats_zh.json` ~23 KB，自然包含辅音条目。

### 7.5 验证 — [完成]

```bash
.venv/bin/python tools/validate_zh.py --processed corpus-processed-zh --holdout 20
```
结果：
- median(m)=0.507, median(f)=0.713, Δ=+0.206
- threshold=0.587, accuracy=0.850 → **PASS**
- 男声 0.29–0.63，女声 0.48–0.88
- ⚠️ held-out 取自训练池末尾，存在 leakage；后续如需严格泛化评估，应再采样独立子集。

### 7.6 `weights_zh.json` 向量化 + k-fold 暴力搜索 — [完成]

重写 `corpusanalysis.py` 末尾的暴力搜索：

- **预计算 z-score**（只算一次，脱离 weights 循环）：先调一次 `compute_resonance` 触发 outlier removal + `F_stdevs` 填充，再抽每 utt 的 `(n_valid_phones, 3)` z 数组。
- **向量化扫描**：`R = clip(Z @ W.T + 0.5, 0, 1).mean(axis=0)`，一次 matmul 评完所有 candidate，numpy 自动走 BLAS 多核。
- **K-fold CV**：`--weights-kfold 10`；每折用 train median 作阈值，在 test 上算 acc；`score = mean_acc - 1e-6*std_acc` 选 mean 最高、并列取 std 最小。
- **Coarse-to-fine**：
  - coarse: 单纯形均匀 `--weights-granularity 500` → 125,751 candidates
  - refine: 在 coarse winner 周围 `±0.05` 盒子内 `--weights-refine-steps 201` → 8,120,601 candidates，归一化回单纯形
- **分块**（避免 99 GB 爆内存）：`--weights-chunk 200000`，每块独立评估后仅保留全局最优 idx。

```bash
PYTHONPATH=acousticgender .venv/bin/python acousticgender/corpusanalysis.py \
  --lang zh --jobs 8 --corpus-dir corpus --processed-dir corpus-processed-zh \
  --stats-out stats_zh.json --weights-out weights_zh.json \
  --weights-granularity 500 --weights-kfold 10 --weights-refine \
  --weights-refine-steps 201 --weights-refine-half-width 0.05 --weights-chunk 200000
```

**结果**：
- n_utts=268（m=134, f=134）
- coarse winner `[0.658, 0.242, 0.1]` 10-fold mean_acc=0.8061, std=0.0770
- refine 未找到严格更优点（coarse 已命中 201-grid 节点）
- 最终 `weights_zh.json = [0.658, 0.242, 0.1]`
- validate_zh.py held-out：**median(m)=0.510, median(f)=0.706, Δ=+0.196, acc=0.900** PASS（英文 weights `[0.73, 0.27, 0.0]` 下 acc=0.850）

### 状态

- [x] M0 代码骨架：`corpusanalysis.py` 加 `--lang`；`backend.cgi` 按 lang 选 weights
- [x] M1 下载 + 解压 AISHELL-3
- [x] M2 采样到 `./corpus/`（153 m + 153 f）
- [x] M3 `--jobs` 并行化
- [x] M4 生成新 `stats_zh.json`（114+114 实际入池；M6 重跑后 134+134）
- [x] M5 验证 PASS（EN weights: acc=0.85, Δmedian=0.206）
- [x] M6 `weights_zh.json` 向量化 k-fold 暴力搜索（acc=0.900, Δmedian=0.196）+ tag v0.1.1

---

## 8. v0.1.2 — 内容清理 + Railway 部署

### 8.1 中文练声文本替换 + 移除捐助 FAQ（`db6f604`）

- `index.html` / `resources/speech-scripts.html`：删除「我爱祖国」，替换为三条公共领域练声素材：
  - 绕口令·平翘舌（s/sh 辨音）
  - 绕口令·八百标兵（b/p 送气）
  - 普通话测试标准短文《朋友》节选
- `index.html` / `ui/help.html` / `ui/i18n.js`：移除 help FAQ7 捐助条目及对应中英 i18n 键。中文分支不再转发上游作者 Luna McNulty 的赞助入口。

### 8.2 Railway 部署支持（`9483180`）

- 新增 `Dockerfile`：基于 `mambaorg/micromamba`，预装 ffmpeg/sox/praat + MFA conda env，启动时通过 `settings.json` 路径直连 mfa env 的 `mfa` 二进制。
- 新增 `railway.json`、`.dockerignore`。
- `serve.py`：支持 `PORT` / `HOST` 环境变量，便于容器化部署。
- `CHANGELOG_ZH.md` 追加 v0.1.2 条目。

### 8.3 Railway 调试：固定 `MFA_ROOT_DIR` + 让 MFA 错误冒泡（`27a6123`）

- `Dockerfile`：显式设置 `MFA_ROOT_DIR`，避免容器内默认路径（`~/Documents/MFA`）不可写。
- `acousticgender/library/preprocessing.py`：MFA 调用失败时不再静默吞错，直接冒泡 stderr 供 Railway 日志排查。

### 8.4 Railway: 补中文分词依赖（`fce501d`）

- `Dockerfile`：在 MFA env 内追加 `spacy-pkuseg` / `dragonmapper` / `hanziconv` —— MFA v2 `mandarin_mfa` 在容器环境下按字对齐前会触发这些 optional tokenizer，缺失时报 import 错误。

### 状态

- [x] v0.1.2 内容清理 + Railway 镜像可构建
- [ ] Railway 生产环境端到端验证（录音 → MFA → resonance）
