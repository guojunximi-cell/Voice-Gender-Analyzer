# 色系决策：共鸣/音高 → 性别方向

## 当前方案

Phone-Level Timeline 使用 **柔和蓝 → 暖白 → 柔粉** 的 9 档 diverging 色系。蓝侧 = 男声方向，粉侧 = 女声方向。中性点 = 暖白（`#EDE8E4`）。

## 演进历史

### v1 (Cividis) — 已弃用
最早用 Cividis（单调蓝→黄），刻意规避 pink/blue 性别编码。问题：它是"顺序"色系，没有中性点，视觉上无法表达"方向"。

### v2 (ColorBrewer RdBu) — 已弃用
换成 RdBu（反转）+ 饱和红蓝。问题：
- 深红 `#B2182B` 饱和度过高，视觉上过于"医疗/警示"
- 与应用现有 UI（Engine A 的 male/female tiles 已用蓝粉）视觉不一致
- 中性点为纯白，在色条中看起来像"断点"而非连续过渡

### v3 (当前) — 柔和蓝粉

理由：
1. **视觉一致性**：Engine A 的 male/female 指示色已经是蓝粉，timeline 色系跟齐
2. **文化语境**：trans pride flag 本身就是蓝粉白。色系在 voice training community 已被 reclaim，不是单向符号强加
3. **降饱和**：避免"性别玩具"联想，使用灰蓝/柔粉而非鲜艳色
4. **暖白中性**：`#EDE8E4` 而非 `#F5F5F5`，让色带看起来是一条连续缎带

## 色档

| Stop | Hex | 含义 |
|------|------|------|
| 0 | `#3A6B8D` | 深冷蓝（强男声方向）|
| 1 | `#5B8FB0` | 锚点 |
| 2 | `#8BB0C9` | 中蓝 |
| 3 | `#BDD3E0` | 浅蓝 |
| 4 | `#EDE8E4` | **暖白中性**（构造中点）|
| 5 | `#E6C8D2` | 浅粉 |
| 6 | `#D9A1B6` | 中粉 |
| 7 | `#BC738F` | 深玫瑰 |
| 8 | `#964B69` | 深冷粉（强女声方向）|

## CVD 验证

**方法**：Viénot-Brettel-Mollon 1999 的 sRGB → LMS → dichromat 投影 → LMS → sRGB → Lab → CIE76 ΔE。实现在 `web/src/modules/diverging.js` 的 `_verifyCVD()`；CLI 跑法：

```bash
node tools/diagnose/verify-diverging-cvd.mjs
```

**阈值**：相邻档在 deuteranopia 与 protanopia 视角下的 ΔE₇₆ 都必须 > 3（远高于训练观察者的 JND ~2.3）。

**结果**（2026-04-18）：

```
Adjacent pair         Normal    Deutan    Protan
----------------------------------------------------
#3A6B8D → #5B8FB0     14.02     13.81     14.00
#5B8FB0 → #8BB0C9     14.31     14.96     13.74
#8BB0C9 → #BDD3E0     15.58     16.36     14.87
#BDD3E0 → #EDE8E4     15.59     16.27     13.07
#EDE8E4 → #E6C8D2     14.78      8.87     11.53
#E6C8D2 → #D9A1B6     16.39     10.73     13.29
#D9A1B6 → #BC738F     17.25     14.45     16.31
#BC738F → #964B69     15.16     14.77     15.52
----------------------------------------------------
End-to-end (0 → 8)    45.96     28.35     13.77

Min ΔE₇₆ across CVD views: 8.87   (threshold > 3)  PASS ✓
```

**读数**：
- 最小相邻 CVD ΔE = **8.87**（deut，中性 → 浅粉），约为阈值 3 的 2.95 倍
- End-to-end protan ΔE = 13.77 是 CVD 视角下最弱的跨度，但仍远超 "just noticeable"（通常 ΔE ≈ 2–3 即可感知）
- deuteranopia 视角下中性 → 粉侧的过渡略弱（8.87 / 10.73），这是 L-M 轴丢失的固有代价；已在可接受范围

## 科学依据（resonance/pitch 的中性点）

### 共鸣值

来自 `voiceya/sidecars/visualizer-backend/acousticgender/library/resonance.py`：

```
resonance = clamp(0, 1, w₁·F1_z + w₂·F2_z + w₃·F3_z + 0.5)
```

构造上 **0.5 = 参考语料库均值**。AISHELL-3 训练得出（10-fold CV, n=268, acc=0.900）：

| | 中位数 | 范围 |
|--|--------|------|
| 男声 | 0.507 | ~0.30–0.63 |
| 女声 | 0.713 | ~0.48–0.88 |
| 判别阈值 | **0.587** | — |

### 音高

声音训练文献：
- Gelfer & Mikos (2005): 女声感知阈值 ~180 Hz
- Leung et al. (2018): 训练目标 F0 ≥ 180 Hz
- 通用：男 <165 Hz / 雌雄同体 165–180 Hz / 女 >180 Hz

实现中性点 **165 Hz**，饱和端 [100, 230] Hz。

## 实现文件

- `web/src/modules/diverging.js` — 调色板 + 映射函数 + `_verifyCVD()`
- `tools/diagnose/verify-diverging-cvd.mjs` — CLI 验证脚本
- `web/src/modules/gender-legend.js` — 色条 legend
- `web/src/modules/heatmap-band.js` — 热力带
- `web/src/styles/timeline.css` — `--dv-0` ~ `--dv-8` tokens

Cividis 保留在 `cividis.js` 作为未来 toggle 备份。

## 重新验证

**每次改动 `STOPS` 必须**：
```bash
node tools/diagnose/verify-diverging-cvd.mjs
```
未通过不提交。通过后把新矩阵贴到本文档"CVD 验证 / 结果"段。

## 非目标

- 色彩**不替代**数值。`engine_c.phones[*].resonance` 是原始数值，UI 只做视觉映射
- 色彩**不是性别判定**。色值 0.587 附近的样本不应被解读为"恰好是男/女"
