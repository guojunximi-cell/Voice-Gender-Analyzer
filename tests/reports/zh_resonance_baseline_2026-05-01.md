# zh-CN resonance baseline (2026-05-01)

**Source**: AISHELL-3 train, sampled 50F + 42M speakers, 5 clips/spk concatenated, seed=17.

Sidecar formant ceiling: legacy 5000 Hz (zh not in `_ADAPTIVE_LANGS`).

Speakers analyzed: 92 (50F / 42M).  Dropped: 0.


## Table 1 — per-spk median `resonance` distribution

| sex | n | P5 | P25 | P50 | P75 | P95 | mean |
|---|---|---|---|---|---|---|---|
| F | 50 | 0.490 | 0.612 | 0.683 | 0.842 | 1.000 | 0.721 |
| M | 42 | 0.234 | 0.305 | 0.403 | 0.518 | 0.698 | 0.417 |

## Table 2 — per-vowel z-scores (relative to `stats_zh.json`)

Z is computed against the reference distribution in `stats_zh.json`. Negative ⇒ measurement falls below the reference mean (more male-like in F1/F2 space).  `sat_rate` = fraction of `resonance` values clamped to [0, 0.02] ∪ [0.98, 1].

### F speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| i | 557 | 379 | 2561 | 3232 | +0.01 | +0.54 | +0.36 | 0.46 |
| a | 548 | 953 | 1615 | 2821 | +0.27 | +0.35 | +0.36 | 0.62 |
| o | 390 | 613 | 1416 | 2948 | -0.03 | +0.18 | +0.31 | 0.46 |
| u | 332 | 428 | 1067 | 2930 | -0.09 | -0.04 | +0.21 | 0.47 |
| e | 305 | 634 | 2090 | 3002 | +0.11 | +0.35 | +0.49 | 0.59 |
| ə | 274 | 637 | 1682 | 3035 | +0.12 | +0.26 | +0.53 | 0.65 |
| ow | 208 | 495 | 1101 | 3005 | -0.06 | +0.04 | +0.38 | 0.43 |
| ʐ̩ | 193 | 438 | 1900 | 2870 | +0.03 | +0.30 | +0.48 | 0.31 |
| aw | 178 | 799 | 1276 | 2905 | +0.24 | +0.22 | +0.25 | 0.63 |
| ej | 168 | 473 | 2324 | 3012 | -0.04 | +0.50 | +0.50 | 0.43 |
| aj | 147 | 845 | 1974 | 2841 | +0.23 | +0.54 | +0.53 | 0.47 |
| y | 95 | 366 | 2320 | 2879 | +0.02 | +0.49 | +0.30 | 0.45 |
| z̩ | 94 | 445 | 1758 | 3171 | -0.04 | +0.48 | +0.66 | 0.31 |
| ɥ | 43 | 396 | 2246 | 2814 | +0.22 | +0.33 | +0.27 | 0.35 |

### M speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| i | 468 | 312 | 2167 | 2860 | -0.64 | -0.18 | -0.74 | 0.55 |
| a | 452 | 743 | 1323 | 2527 | -0.89 | -0.84 | -0.34 | 0.76 |
| o | 354 | 492 | 1244 | 2569 | -0.72 | -0.54 | -0.72 | 0.73 |
| u | 306 | 363 | 954 | 2612 | -0.63 | -0.36 | -0.77 | 0.68 |
| ə | 276 | 507 | 1487 | 2604 | -0.68 | -0.47 | -0.51 | 0.67 |
| e | 267 | 489 | 1800 | 2625 | -0.78 | -0.48 | -0.54 | 0.50 |
| ʐ̩ | 176 | 366 | 1576 | 2603 | -0.51 | -1.01 | -0.13 | 0.65 |
| ow | 168 | 418 | 958 | 2663 | -0.76 | -0.67 | -0.77 | 0.75 |
| aw | 141 | 608 | 1045 | 2609 | -1.03 | -1.03 | -0.66 | 0.73 |
| ej | 140 | 401 | 1966 | 2600 | -0.68 | -0.48 | -0.87 | 0.51 |
| aj | 129 | 669 | 1625 | 2469 | -1.02 | -0.69 | -0.48 | 0.78 |
| y | 83 | 295 | 2008 | 2449 | -0.80 | -0.58 | -1.20 | 0.78 |
| z̩ | 61 | 363 | 1417 | 2787 | -0.64 | -0.86 | -0.23 | 0.70 |
| ɥ | 25 | 329 | 1897 | 2378 | -0.36 | -0.89 | -1.35 | 0.44 |

## Table 3 — F2 collapse check (female speakers vs literature)

Literature targets are typical Mandarin female F2 from 鲍怀翘《普通话语音学》 + Lee/Zhang 2008 JASA.  `verdict=COLLAPSE` ⇒ measured F2 < 75 % of literature, indicates Praat ceiling-too-low (5000 Hz mis-resolves F2/F3).

| vowel | n | F2_med (this run) | F2 lit | ratio | verdict |
|---|---|---|---|---|---|
| i | 533 | 2561 | 2700 | 0.95 | ok |
| y | 93 | 2320 | 2300 | 1.01 | ok |
| e | 305 | 2090 | 2200 | 0.95 | ok |
| ej | 166 | 2324 | 2100 | 1.11 | ok |
| ə | 274 | 1682 | 1700 | 0.99 | ok |
| a | 549 | 1615 | 1400 | 1.15 | ok |
| u | 295 | 1067 | 800 | 1.33 | ok |

## Table 4 — 5-zone candidate thresholds for `resonance_zone_key`

Anchored to female P5/P25/P75/P95 from Table 1.  Phase B will commit these as constants in `voiceya/services/audio_analyser/resonance_calibration.py`.

| zone_key | range |
|---|---|
| `clearly_male` | < 0.49 |
| `leans_male` | [0.49, 0.612) |
| `neutral` | [0.612, 0.842) |
| `leans_female` | [0.842, 1.0) |
| `clearly_female` | ≥ 1.0 |

## Decision points

1. **F2 collapse not detected** — current 5000 Hz ceiling holds for zh.  Skip adding zh to `_ADAPTIVE_LANGS`.
2. **Score ceiling is real**: 4/50 F speakers (8 %) saturate `medianResonance` at ≥0.98; F P95 is 1.000.  M side: 0/42 saturate top, 0/42 saturate bottom.  Implication: a five-tier zone with `clearly_female ≥ P95` is degenerate — users in that tier are at the clamp ceiling, not at a 'more female' level.  Recommend setting `clearly_female` boundary at F P75 (Table 1) instead, so the top tier captures the upper quartile of F speakers without requiring saturation.
3. **F-M overlap band**: [0.490, 0.698] is reachable by both sexes' P5–P95 ranges (M P95 = 0.698, F P5 = 0.490).  Inside this band the score isn't sex-discriminative on its own — Phase D summary text should phrase it as 'in shared range' rather than directional.
4. Female–male median gap (P50): +0.280.  Wide enough for percentile-anchored zones (use Table 4 numbers).
5. **Per-vowel score has low diagnostic power** on saturated classes.  F-speaker high-sat vowels: aw(63%), a(62%), e(59%), ə(65%).  M-speaker high-sat vowels: u(68%), a(76%), y(78%), ej(51%), o(73%), aj(78%), i(55%), ow(75%), ʐ̩(65%), ə(67%), aw(73%), z̩(70%).  Phase C per-vowel guidance should display **z_F1 / z_F2 directly** for these (absolute Hz delta to female mean) rather than the clamped resonance score — the z values still carry sub-clamp signal.
6. **Recommended Phase B path** (in order): (a) re-train `stats_zh.json` at 5500 Hz ceiling using AISHELL-3 train (script can mirror `scripts/train_stats_fr.py`); (b) re-run this audit against the new stats — verify /i/ F2_med returns to ≥2200 Hz and F median resonance distribution shifts down (saturation rate drops); (c) add zh to `_ADAPTIVE_LANGS` in `wrapper/ceiling_selector.py`; (d) commit the new Table 4 zone thresholds to `resonance_calibration.py`; (e) keep raw `medianResonance` in the API response — only the **interpretation** layer (zone label, summary text) reads from `resonance_calibration`.
7. AISHELL-3 male sample n=42 — confidence intervals on M side are wider than F's.  If a Phase B decision hinges on M numbers, supplement with THCHS-30 / MAGICDATA male.