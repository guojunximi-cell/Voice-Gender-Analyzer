# zh-CN resonance baseline (2026-05-01)

**Source**: AISHELL-3 train, sampled 50F + 42M speakers, 5 clips/spk concatenated, seed=17.

Sidecar formant ceiling: legacy 5000 Hz (zh not in `_ADAPTIVE_LANGS`).

Speakers analyzed: 92 (50F / 42M).  Dropped: 0.


## Table 1 — per-spk median `resonance` distribution

| sex | n | P5 | P25 | P50 | P75 | P95 | mean |
|---|---|---|---|---|---|---|---|
| F | 50 | 0.554 | 0.718 | 0.802 | 0.917 | 1.000 | 0.808 |
| M | 42 | 0.269 | 0.381 | 0.455 | 0.591 | 0.700 | 0.483 |

## Table 2 — per-vowel z-scores (relative to `stats_zh.json`)

Z is computed against the reference distribution in `stats_zh.json`. Negative ⇒ measurement falls below the reference mean (more male-like in F1/F2 space).  `sat_rate` = fraction of `resonance` values clamped to [0, 0.02] ∪ [0.98, 1].

### F speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| i | 557 | 369 | 1523 | 2837 | -0.06 | -0.59 | +0.07 | 0.46 |
| a | 527 | 912 | 1514 | 2384 | +0.80 | +0.51 | +0.06 | 0.74 |
| o | 389 | 625 | 1391 | 2660 | +0.45 | +0.34 | +0.34 | 0.58 |
| u | 332 | 420 | 1026 | 2676 | +0.12 | -0.08 | +0.34 | 0.50 |
| e | 305 | 603 | 1733 | 2454 | +0.51 | -0.01 | -0.26 | 0.63 |
| ə | 275 | 612 | 1509 | 2385 | +0.62 | +0.03 | -0.09 | 0.68 |
| ow | 208 | 498 | 1094 | 2794 | +0.19 | +0.07 | +0.54 | 0.43 |
| ʐ̩ | 193 | 435 | 1766 | 2331 | +0.28 | +0.26 | -0.21 | 0.43 |
| aw | 177 | 806 | 1271 | 2533 | +0.84 | +0.36 | +0.12 | 0.78 |
| ej | 168 | 467 | 1768 | 2610 | +0.15 | -0.02 | +0.28 | 0.51 |
| aj | 147 | 842 | 1805 | 2324 | +0.73 | +0.76 | -0.07 | 0.72 |
| y | 95 | 383 | 2134 | 2770 | +0.45 | +0.42 | +0.62 | 0.64 |
| z̩ | 94 | 422 | 1599 | 2080 | +0.11 | +0.41 | -0.87 | 0.47 |
| ɥ | 43 | 397 | 2013 | 2618 | +0.06 | +0.31 | +0.21 | 0.35 |

### M speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| i | 468 | 312 | 2128 | 2795 | -0.52 | +0.52 | -0.04 | 0.28 |
| a | 452 | 748 | 1321 | 2462 | -0.09 | -0.31 | +0.25 | 0.51 |
| o | 354 | 483 | 1234 | 2522 | -0.41 | -0.23 | +0.04 | 0.44 |
| u | 306 | 362 | 953 | 2572 | -0.43 | -0.31 | +0.07 | 0.55 |
| ə | 276 | 505 | 1471 | 2569 | -0.08 | -0.10 | +0.32 | 0.52 |
| e | 267 | 490 | 1784 | 2550 | -0.31 | +0.13 | +0.04 | 0.42 |
| ʐ̩ | 176 | 365 | 1553 | 2509 | -0.41 | -0.63 | +0.23 | 0.47 |
| ow | 168 | 416 | 961 | 2607 | -0.57 | -0.55 | +0.12 | 0.57 |
| aw | 141 | 606 | 1045 | 2579 | -0.39 | -0.73 | +0.22 | 0.55 |
| ej | 140 | 400 | 1952 | 2523 | -0.52 | +0.46 | -0.01 | 0.32 |
| aj | 129 | 661 | 1595 | 2380 | -0.41 | -0.02 | +0.10 | 0.44 |
| y | 83 | 291 | 1978 | 2402 | -0.68 | -0.00 | -0.63 | 0.51 |
| z̩ | 61 | 356 | 1416 | 2781 | -0.47 | -0.27 | +0.54 | 0.49 |
| ɥ | 25 | 327 | 1887 | 2370 | -0.40 | +0.00 | -0.59 | 0.12 |

## Table 3 — F2 collapse check (female speakers vs literature)

Literature targets are typical Mandarin female F2 from 鲍怀翘《普通话语音学》 + Lee/Zhang 2008 JASA.  `verdict=COLLAPSE` ⇒ measured F2 < 75 % of literature, indicates Praat ceiling-too-low (5000 Hz mis-resolves F2/F3).

| vowel | n | F2_med (this run) | F2 lit | ratio | verdict |
|---|---|---|---|---|---|
| i | 485 | 1523 | 2700 | 0.56 | COLLAPSE |
| y | 83 | 2134 | 2300 | 0.93 | ok |
| e | 303 | 1733 | 2200 | 0.79 | low |
| ej | 157 | 1768 | 2100 | 0.84 | low |
| ə | 274 | 1509 | 1700 | 0.89 | ok |
| a | 549 | 1514 | 1400 | 1.08 | ok |
| u | 309 | 1026 | 800 | 1.28 | ok |

## Table 4 — 5-zone candidate thresholds for `resonance_zone_key`

Anchored to female P5/P25/P75/P95 from Table 1.  Phase B will commit these as constants in `voiceya/services/audio_analyser/resonance_calibration.py`.

| zone_key | range |
|---|---|
| `clearly_male` | < 0.554 |
| `leans_male` | [0.554, 0.718) |
| `neutral` | [0.718, 0.917) |
| `leans_female` | [0.917, 1.0) |
| `clearly_female` | ≥ 1.0 |

## Decision points

1. **F2 collapse confirmed** on /i/ (worst: /i/ measured 1523 Hz vs literature 2700 Hz = 56%).  Same fingerprint as fr-FR before adaptive ceiling.  Path: re-train `stats_zh.json` at 5500 Hz ceiling, then add zh to `_ADAPTIVE_LANGS`. Without re-training, simply enabling adaptive ceiling for zh would over-correct (stats_zh's F2 means are baked at 5000 Hz; bumping the ceiling shifts every z_F2 positive, drives all male voices into female zone — exactly the Phase 8 regression that put zh out of `_ADAPTIVE_LANGS` in the first place).
   Soft-low (75–85 % of literature, watch list): /e, /ej/.
2. **Score ceiling is real**: 9/50 F speakers (18 %) saturate `medianResonance` at ≥0.98; F P95 is 1.000.  M side: 0/42 saturate top, 0/42 saturate bottom.  Implication: a five-tier zone with `clearly_female ≥ P95` is degenerate — users in that tier are at the clamp ceiling, not at a 'more female' level.  Recommend setting `clearly_female` boundary at F P75 (Table 1) instead, so the top tier captures the upper quartile of F speakers without requiring saturation.
3. **F-M overlap band**: [0.554, 0.700] is reachable by both sexes' P5–P95 ranges (M P95 = 0.700, F P5 = 0.554).  Inside this band the score isn't sex-discriminative on its own — Phase D summary text should phrase it as 'in shared range' rather than directional.
4. Female–male median gap (P50): +0.346.  Wide enough for percentile-anchored zones (use Table 4 numbers).
5. **Per-vowel score has low diagnostic power** on saturated classes.  F-speaker high-sat vowels: aw(78%), a(74%), u(50%), o(58%), e(63%), ej(51%), aj(72%), ə(68%), y(64%).  M-speaker high-sat vowels: u(55%), a(51%), y(51%), ow(57%), ə(52%), aw(55%).  Phase C per-vowel guidance should display **z_F1 / z_F2 directly** for these (absolute Hz delta to female mean) rather than the clamped resonance score — the z values still carry sub-clamp signal.
6. **Recommended Phase B path** (in order): (a) re-train `stats_zh.json` at 5500 Hz ceiling using AISHELL-3 train (script can mirror `scripts/train_stats_fr.py`); (b) re-run this audit against the new stats — verify /i/ F2_med returns to ≥2200 Hz and F median resonance distribution shifts down (saturation rate drops); (c) add zh to `_ADAPTIVE_LANGS` in `wrapper/ceiling_selector.py`; (d) commit the new Table 4 zone thresholds to `resonance_calibration.py`; (e) keep raw `medianResonance` in the API response — only the **interpretation** layer (zone label, summary text) reads from `resonance_calibration`.
7. AISHELL-3 male sample n=42 — confidence intervals on M side are wider than F's.  If a Phase B decision hinges on M numbers, supplement with THCHS-30 / MAGICDATA male.