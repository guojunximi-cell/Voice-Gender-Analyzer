# 项目完整流水线说明（Pipeline）

本文件描述 `gender-voice-visualization`（中文分支 v0.1.2）从用户点击「添加片段」到图表落点的全过程，以及离线训练 `stats_zh.json` / `weights_zh.json` 的数据链。前端已锁定中文单语，但 **后端仍保留完整的双语代码路径**，本文一并说明。

---

## 0. 总览

```
浏览器 (ui/new-clip.html)
   │  multipart/form-data：recording + transcript + lang='zh'
   ▼
backend.cgi
   │  lang 归一化：zh-* → 'zh'，其它 → 'en'
   │  tmp_dir = settings['recordings'] + random_id()
   ▼
preprocessing.process(file, transcript, tmp_dir, lang)
   ├─ ffmpeg 转码 + silencedetect 静音段抽取
   ├─ sox noiseprof + noisered 降噪
   ├─ ffmpeg 再转 16kHz mono WAV（MFA 输入规范）
   ├─ 写 transcript（中文走字符级空格分词）
   ├─ MFA align → TextGrid（模型: mandarin_mfa | english_mfa）
   └─ Praat textgrid-formants.praat → TSV(time,phone,F0,F1,F2,F3)
   ▼
phones.parse(tsv, lang)
   └─ TSV + 词典 (mandarin_dict.txt | cmudict.txt) → {words, phones}
   ▼
resonance.compute_resonance(data, weights, lang)
   ├─ 每维 F 做 |F-μ|>2σ 离群剔除
   ├─ 按音素类别查 stats → z-score：(F-stats.mean) / stats.stdev
   ├─ 仅对元音计算 resonance = clip(0,1, w1·z1 + w2·z2 + w3·z3 + 0.5)
   └─ 汇总 mean/median/stdev of pitch & resonance
   ▼
backend.cgi → print(JSON)
   ▼
浏览器渲染（voice-graph）：X = resonance, Y = pitch
```

---

## 1. 前端提交阶段

**入口**：`ui/new-clip.html` 的 `submitAudio()`。

- 表单组装 `FormData`：
  - `recording`：上传文件或麦克风录制的 Blob（wav/mp3/m4a/opus/webm…）
  - `transcript`：用户文本（可手写或选预置脚本 `resources/speech-scripts.html`）
  - `lang`：当前分支硬编码 `'zh'`（`ui/new-clip.html:190`）
  - `referrer`、`screen-width`、`screen-height`：遥测
- POST 到 `/backend.cgi`。

**渲染层**：`ui/voice-graph.js` 收到后端 JSON 后，把每个 phone 映射到二维坐标：
- Y 轴 = pitch（F0），上下界 `50 Hz – 400 Hz`（`voice-graph.js:13-14`）
- X 轴 = resonance，`0-100%`
- `ui/util.js:27` 的 `pitchPercent = (pitch - 50) / 350`

---

## 2. 后端入口 `backend.cgi`

请求解析：用 `email.parser.BytesParser` 手工解析 multipart（不依赖 `cgi` 模块，Python 3.13+ 已废弃 `cgi`）。

关键代码流：

```python
lang = get_field('lang', default='en', decode=True)
if lang and lang.startswith('zh'): lang = 'zh'
else:                              lang = 'en'          # backend.cgi:39-44

tmp_dir = settings['recordings'] + random_id()          # backend.cgi:49
praat_output = preprocessing.process(uploaded_file, transcript, tmp_dir, lang)
data = phones.parse(praat_output, lang)
weights_file = 'weights_zh.json' if lang == 'zh' and os.path.exists('weights_zh.json') else 'weights.json'
resonance.compute_resonance(data, weights, lang)
print(json.dumps(data))
```

MFA 无对齐输出时直接抛 `RuntimeError: MFA produced no alignment output`（`backend.cgi:54-55`），以便 Railway 部署时看到 stderr 冒泡。

---

## 3. `preprocessing.process`（文件级阶段）

源：`acousticgender/library/preprocessing.py`

### 3.1 降噪（可回退）

1. `ffmpeg -i orig format.wav`：统一转 wav。
2. `ffmpeg -af silencedetect=n=-30dB:d=0.5` 扫描静音段。
3. `ffmpeg -af aselect=...` 把静音段抽出来，形成 `silence.wav`。
4. `sox silence.wav -n noiseprof noise.prof`：只用静音段采噪声谱。
5. `sox format.wav clean.wav noisered noise.prof 0.2`：对原音频做频谱减法。

**回退逻辑**：`try/except` 包住整段——录音开头即静音会让 `silencedetect` 产出不配对的 `silence_end`，`aselect between(t,,X)` 会语法错；捕获后直接用 `input_file` 原文件进入 MFA，不强行要求降噪成功（`preprocessing.py:25-60`）。

### 3.2 MFA 对齐准备

```python
ffmpeg -i clean.wav -acodec pcm_s16le -ac 1 -ar 16000 corpus/recording.wav
```

MFA 只吃 16 kHz 单声道 PCM16 wav。

**transcript 归一化**（中英分歧）：
- 英文：原文直接写盘。
- 中文：`re.findall(r'[\u4e00-\u9fff]', transcript)` 把汉字逐字切出，用空格拼接写盘（`preprocessing.py:77-82`）。若不做，整句会被 MFA 当成单个 OOV 词 → `<unk>`，TextGrid 里所有音素都是 `spn`。

### 3.3 MFA 命令

```bash
mfa align ./corpus/ mandarin_mfa mandarin_mfa ./output/ --clean --beam 100 --retry_beam 400
```

- 词典和声学模型都叫 `mandarin_mfa`（同名两份：词典文件 + 声学模型目录）。
- `--beam 100 --retry_beam 400`：比默认（10/40）放宽，避免中文短句 `Beam too narrow` 失败。
- Linux 直接调 `settings['mfa']` shim；Windows 用 `python mfa-script.py` 绕开 shebang 问题（`preprocessing.py:93-110`）。
- 环境：必设 `CONDA_PREFIX`，并把 `scripts_dir` 前置到 `PATH`——否则 conda env 里的 `kaldi`/`openfst` 等 DLL 找不到。

MFA 失败走 `CalledProcessError` 分支：把 stderr 尾部 800 字符并入 `RuntimeError` 冒泡（`preprocessing.py:127-131`）。

### 3.4 Praat 抽共振峰

对每个 `(wav, TextGrid)` 对调用：

```
praat --run textgrid-formants.praat recording.wav recording.TextGrid
```

脚本 `textgrid-formants.praat`：

```praat
To Pitch: 0, 75, 600                       # F0 搜索范围
To Formant (burg)... 0 5 5000 0.025 50     # 最多 5 个共振峰，上界 5 kHz

for i in 1..numPhonemes:
    midpoint = (startTime + endTime) / 2
    f0 = Pitch value at midpoint
    f1,f2,f3 = Formant values at midpoint
    print startTime \t phoneme \t f0 \t f1 \t f2 \t f3
```

输出是两块 TSV：
```
Words:
0.0\tWORD1
0.37\tWORD2
...
Phonemes:
0.0\tph1\tf0\tf1\tf2\tf3
0.12\tph2\tf0\tf1\tf2\tf3
...
```

该字符串既落盘为 `*.tsv`（便于调试），也直接 `return` 给上层。

### 3.5 清理

`shutil.rmtree(tmp_dir)`（`preprocessing.py:163`）——请求结束把整个工作目录删掉，不保留原始录音。**离线 corpusanalysis 并行场景下这一行必须绕开**，否则并发 worker 会误删彼此 TSV。

---

## 4. `phones.parse`（TSV → 结构化）

源：`acousticgender/library/phones.py`

1. 按 `"Words:"` / `"Phonemes:"` 分节读 TSV。
2. 加载词典：
   - 英文 `cmudict.txt`（ARPABET，空格分隔，ISO-8859-1）
   - 中文 `mandarin_dict.txt`（IPA，tab 分隔，第 6 列为音素序列，UTF-8-BOM）
3. `data['words']`：每个词 `{time, word, expected: [音素序列...]}`；英文 word 取 upper，中文保留原字。
4. `data['phones']`：每个音素 `{time, phoneme, word_index, word, expected, F: [F0,F1,F2,F3]}`。
   - `expected` 是**词典告知的理论音素**（用于后续 z-score 的分母选择——实际说出的 phoneme 可能带 MFA 替换，但理论值更稳）。
   - `F` 里 `'--'` 标记（Praat 在边界失败时）被转为 `None`。

---

## 5. `resonance.compute_resonance`（核心特征工程）

源：`acousticgender/library/resonance.py`

### 5.1 离群剔除

对 `F0/F1/F2/F3` 四维独立做：

```python
if |F[i] - mean| / stdev > 2:
    phone.outlier = True
    phone.F[i] = None
```

（`resonance.py:24-41`）

剔除是 **就地把该维置 None**，不删 phone。后续 pitch/resonance 汇总时用 `phone.get('outlier')` 过滤。

### 5.2 z-score

加载 `stats_zh.json`（zh）或 `stats.json`（en）。schema：

```json
{
  "IY1": [
    {"mean": 171.9, "stdev": 59.3, "median": 165.6, "max": 478.4, "min": 75.5},  // F0
    {"mean": 375.2, "stdev": 133.9, ...},   // F1
    {"mean": 2111.8, ...},                  // F2
    {"mean": 2708.1, ...}                   // F3
  ],
  "AO1": [...],
  ...
}
```

即**每个音素 × 每个 formant 维度** 的聚合统计。

**音素 key 归一化（中文分歧）**：
```python
if lang == 'zh':
    phoneme_key  = _strip_tone(phone['phoneme'])   # 去掉 ˥˦˧˨˩ 声调标记
    expected_key = _strip_tone(phone['expected'])
```
MFA `mandarin_mfa` 的音素带声调后缀（如 `a˥˧`），但 stats 里按无声调 IPA 聚合，必须去声调才能查表（`resonance.py:47-58`）。

每个 formant 维度算：
```
F_stdevs[i] = (phone.F[i] - stats[expected_key][i].mean) / stats[expected_key][i].stdev
```

### 5.3 只对元音计算 resonance

```python
if lang == 'zh':
    isVowel = _strip_tone(phoneme) in ZH_VOWELS
else:
    isVowel = any(c in "AEIOUY" for c in phoneme)
```

`ZH_VOWELS = {'a','aj','aw','e','ej','i','io','o','ow','u','y','ə','ɥ','ʐ̩','z̩'}` —— 含两个「零韵母」syllabic consonant（`ʐ̩` 对应 zhi/chi/shi/ri；`z̩` 对应 zi/ci/si）。

resonance 公式：

```
resonance = clamp(0, 1,  w1·z_F1 + w2·z_F2 + w3·z_F3 + 0.5)
```

- 0.5 是中心偏置：z-score=0（完全符合群体均值）时 resonance=0.5。
- `clamp(0,1)` 把输出裁到 [0,1]，便于前端直接当百分比。
- `weights` 来自 `weights_zh.json = [0.658, 0.242, 0.1]`（中文）或 `weights.json = [0.7321, 0.2679, 0]`（英文）。**必须满足 sum ≈ 1**，否则 `assert` 直接挂。

### 5.4 汇总统计

```python
data['meanPitch']   = mean of phone.F[0] for non-outliers
data['medianPitch'] = median of same
data['stdevPitch']  = stdev of same
# resonance 同理
```

前端详情面板展示这些。

---

## 6. 返回 JSON Schema

```json
{
  "words":  [{"time": 0.0, "word": "你好", "expected": ["n","i","x","aw",null, ...]}, ...],
  "phones": [
    {
      "time": 0.12, "phoneme": "a˥˧",
      "word_index": 0, "word": {...}, "word_time": 0.0,
      "expected": "a",
      "F": [186.4, 712.0, 1301.5, 2834.2],   // None 表示该维 outlier 或 Praat 失败
      "F_stdevs": [..., 0.42, -0.31, 0.08],  // 仅中段三维通常有值
      "resonance": 0.63                      // 仅元音有
    },
    ...
  ],
  "mean":  {"F": [ ... ]},
  "stdev": {"F": [ ... ]},
  "meanPitch": 198.4, "medianPitch": 192.1, "stdevPitch": 31.2,
  "meanResonance": 0.58, "medianResonance": 0.60, "stdevResonance": 0.11
}
```

错误路径：`{"error": "...", "trace": "..."}`。

---

## 7. 前端渲染

- `ui/index.js` 收到响应后构造 `Clip`，填入 `globalState.clips`。
- `ui/voice-graph.js` 为每个 phone 画一个点：
  - `cx = resonance · width`
  - `cy = (1 - (F0-50)/350) · height`（注意 Y 轴反向：高音在上）
- 聚合点（clip 的 median/mean）用更大的圆 + 颜色区分。
- 详情面板列 mean/median/stdev pitch & resonance。

---

## 8. 中英分歧一览（改动任何一项都要查这张表）

| 层级 | 英文路径 | 中文路径 | 源码位置 |
|------|----------|----------|----------|
| transcript 预处理 | 原样写盘 | 字符级切空格 | `preprocessing.py:77-82` |
| MFA 模型 | `english_mfa` | `mandarin_mfa`（声学 v2.0.0，v3 音素集不兼容） | `preprocessing.py:87` |
| 词典 | `cmudict.txt`（ARPABET） | `mandarin_dict.txt`（IPA, tab, col6） | `phones.py:26-39` |
| 词 key | `.upper()` | 保留原字 | `phones.py:44` |
| phoneme key 归一 | 无 | `_strip_tone()` 去 `˥˦˧˨˩` | `resonance.py:48-49` |
| 元音判定 | `A/E/I/O/U/Y` 字符 | `ZH_VOWELS` 集合含零韵母 | `resonance.py:66-74` |
| stats 文件 | `stats.json` | `stats_zh.json`（AISHELL-3 聚合） | `resonance.py:43` |
| weights | `weights.json = [.73, .27, 0]` | `weights_zh.json = [.658, .242, .1]` | `backend.cgi:56` |

前端现在只走 `lang='zh'` 路径，但以上代码分支全部保留，改回双语只需在 `ui/new-clip.html` 恢复 `<select id="lang-select">` 并还原 `formData.append('lang', ...)` 取值。

---

## 9. 离线训练链（生成 stats / weights）

源：`acousticgender/corpusanalysis.py`

```
corpus/<spk>/<utt>.{wav,txt}  （AISHELL-3 采样，见 tools/build_zh_corpus.py）
   │
   ▼
[并行 ProcessPool] _process_one(spk_dir)
   │  每 worker 独立 MFA_ROOT_DIR，软链 pretrained_models / models / extracted_models
   │  走与线上完全相同的 preprocessing.process（去掉 rmtree）→ Praat TSV 落盘
   ▼
processed-zh/<spk>/<utt>.tsv
   │
   ▼
聚合阶段：按音素收集 F0/F1/F2/F3 样本 → mean/median/stdev/max/min
   │  中文在聚合时 _strip_tone()，把 a˥˧ 和 a˧˩ 归并为 a
   ▼
stats_zh.json
   │
   ▼ （若未传 --skip-weights）
权重搜索：
   1. 粗搜：在 simplex {w1+w2+w3=1, wi∈[0,1], step=1/granularity} 上穷举
   2. K-fold (默认 10) CV：对每个候选 w，算 held-out 说话人
      median(resonance | male) < median(resonance | female) 的比例 + 分离度
   3. 可选 --weights-refine：在粗搜 winner 周围 ±0.05 以 201^3 网格分块精搜
   ▼
weights_zh.json
```

**并发约束**：
- 每 worker 必须独立 `MFA_ROOT_DIR`，否则 MFA 并发写 `command_history.yaml` 会崩。
- `_process_one` 不能调用带 `shutil.rmtree(tmp_dir)` 的完整 `preprocessing.process`；定制版本保留 TSV。

**验证**：`tools/validate_zh.py --processed corpus-processed-zh --holdout 20` 跑 held-out 20 人，要求 `median(m) < median(f)` 且分类 acc ≥ 0.85。

---

## 10. 关键路径依赖 & 已知坑

- `settings.json`：`ffmpeg` / `sox` / `praat` / `mfa` 都用**绝对路径**，所以 `serve.py` 不需要切到 `mfa` conda env，但必须在装了 `maxminddb` / `python-magic` 的 `.venv` 里跑。
- `mandarin_mfa` 词典只发到 v2.0.0；v3 声学模型音素集不兼容（`80125 pronunciations ignored`），下载时必须 `--version 2.0.0`。
- `ffmpeg silencedetect` 对开头即静音的录音产出不配对 `silence_end`——`preprocessing.py` 的 try/except 回退到原文件，**不可去掉**。
- Railway 部署：容器内 `~/Documents/MFA` 不可写，`Dockerfile` 显式设置 `MFA_ROOT_DIR=/tmp/mfa`；`spacy-pkuseg` / `dragonmapper` / `hanziconv` 是 `mandarin_mfa` 字对齐的隐式依赖，缺失会 ImportError。

---

## 11. 相关入口一览

| 文件 | 作用 |
|------|------|
| `serve.py` | 本地开发 CGIHTTPServer（读 `PORT`/`HOST`） |
| `build.cgi` | Jinja 渲染 `ui/base.html` → `index.html` |
| `backend.cgi` | 线上请求入口，见第 2 节 |
| `acousticgender/library/preprocessing.py` | 第 3 节 |
| `acousticgender/library/phones.py` | 第 4 节 |
| `acousticgender/library/resonance.py` | 第 5 节 |
| `acousticgender/corpusanalysis.py` | 第 9 节离线训练 |
| `tools/build_zh_corpus.py` | 从 AISHELL-3 采样到 `corpus/` |
| `tools/validate_zh.py` | Held-out 回归测试 |
| `textgrid-formants.praat` | Praat 共振峰抽取脚本（第 3.4 节） |
| `settings.json` | 二进制工具绝对路径 + dev/logs/recordings 配置 |
