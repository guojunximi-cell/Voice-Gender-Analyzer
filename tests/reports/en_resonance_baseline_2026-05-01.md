# en-US resonance baseline (2026-05-01)

**Source**: hand-curated VCTK + CMU-Arctic + test fixtures at `/mnt/d/project_vocieduck/ablation/audio/en` (cis_female_en + cis_male_en).  Total clips: 63; speakers: 23.  Per-spk median is the median of that speaker's clip-medians.

Sidecar formant ceiling: pinned 5000 Hz (en NOT in `_ADAPTIVE_LANGS`).  stats.json baseline: cmudict-derived, 5000 Hz extraction (upstream).

**⚠ Small sample**: ~16 unique speakers total — P5/P95 estimates have wide CIs.  Treat as directional, not as a calibration anchor without a larger corpus (CV en, LibriSpeech).


## Table 1 — per-spk median `resonance` distribution

| sex | n_spk | P5 | P25 | P50 | P75 | P95 | mean |
|---|---|---|---|---|---|---|---|
| F | 14 | 0.703 | 0.860 | 0.921 | 1.000 | 1.000 | 0.893 |
| M | 9 | 0.411 | 0.482 | 0.581 | 0.693 | 0.847 | 0.589 |

## Table 2 — per-vowel z-scores (relative to `stats.json`)

ARPABET phones with stress digits stripped (IY1/IY2/IY0 → IY).  Z relative to the female reference distribution in `stats.json`.

### F speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| AH | 205 | 524 | 1674 | 2890 | +0.43 | +0.39 | +0.78 | 0.58 |
| IH | 96 | 491 | 1984 | 2865 | +0.46 | +0.35 | +0.76 | 0.58 |
| IY | 82 | 408 | 2399 | 2920 | +0.30 | +0.60 | +0.73 | 0.50 |
| AE | 65 | 788 | 1753 | 2743 | +0.45 | +0.34 | +0.82 | 0.69 |
| EY | 64 | 519 | 2243 | 2870 | +0.32 | +0.57 | +0.75 | 0.47 |
| ER | 59 | 528 | 1677 | 2376 | +0.34 | +1.13 | +0.80 | 0.60 |
| EH | 55 | 708 | 1882 | 2635 | +0.94 | +0.90 | +0.69 | 0.78 |
| AA | 34 | 781 | 1205 | 2873 | +0.57 | +0.33 | +1.16 | 0.79 |
| UW | 28 | 426 | 1841 | 2792 | +0.21 | +0.51 | +0.70 | 0.46 |
| AY | 26 | 727 | 1794 | 2782 | -0.50 | +1.57 | +0.98 | 0.44 |
| OW | 18 | 560 | 1233 | 2809 | +0.56 | -0.26 | +0.76 | 0.72 |
| AO | 15 | 617 | 986 | 2948 | +0.03 | -0.42 | +0.94 | 0.73 |

### M speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| AH | 117 | 429 | 1494 | 2589 | -0.18 | -0.14 | +0.07 | 0.46 |
| IH | 73 | 411 | 1708 | 2543 | -0.21 | -0.32 | -0.10 | 0.49 |
| ER | 40 | 433 | 1419 | 2216 | -0.47 | +0.05 | +0.45 | 0.47 |
| IY | 35 | 316 | 2094 | 2716 | -0.54 | -0.06 | -0.01 | 0.33 |
| EH | 29 | 553 | 1588 | 2494 | -0.34 | -0.16 | +0.27 | 0.52 |
| EY | 28 | 446 | 1860 | 2474 | -0.34 | -0.42 | -0.66 | 0.43 |
| AE | 26 | 585 | 1539 | 2591 | -0.73 | -0.33 | +0.38 | 0.69 |
| AA | 22 | 586 | 1053 | 2607 | -0.81 | -0.54 | +0.53 | 0.50 |
| UW | 18 | 364 | 1760 | 2585 | -0.26 | +0.18 | +0.09 | 0.22 |
| AO | 15 | 508 | 967 | 2441 | -0.66 | -0.50 | -0.18 | 0.62 |
| AY | 14 | 542 | 1681 | 2480 | -1.77 | +1.06 | +0.19 | 0.93 |
| OW | 3 | 482 | 1471 | 2523 | -0.37 | +0.15 | -0.26 | 0.00 |

## Table 3 — F2 collapse check (female speakers vs Hillenbrand 1995)

| vowel | n | F2_med (this run) | F2 lit | ratio | verdict |
|---|---|---|---|---|---|
| IY | 72 | 2399 | 2960 | 0.81 | low |
| IH | 93 | 1984 | 2350 | 0.84 | low |
| EH | 55 | 1882 | 2190 | 0.86 | ok |
| EY | 60 | 2243 | 2350 | 0.95 | ok |
| AE | 65 | 1753 | 2050 | 0.86 | ok |
| AH | 205 | 1674 | 1545 | 1.08 | ok |
| AA | 33 | 1205 | 1130 | 1.07 | ok |
| AO | 15 | 986 | 840 | 1.17 | ok |
| OW | 18 | 1233 | 960 | 1.28 | ok |
| UH | 0 | — | 1120 | — | n<5 |
| UW | 28 | 1841 | 1100 | 1.67 | ok |
| AW | 0 | — | 1290 | — | n<5 |
| AY | 25 | 1794 | 1700 | 1.06 | ok |
| OY | 2 | — | 1100 | — | n<5 |
| ER | 59 | 1677 | 1590 | 1.05 | ok |

## Table 4 — 5-zone candidate thresholds (en F percentiles)

| zone_key | range |
|---|---|
| `clearly_male` | < 0.703 |
| `leans_male` | [0.703, 0.86) |
| `neutral` | [0.86, 1.0) |
| `leans_female` | [1.0, 1.0) |
| `clearly_female` | ≥ 1.0 |

## Decision points

1. **F2 soft-low** on /IY, /IH/ — below Hillenbrand but >75 %.  Adding en to adaptive ceiling would help marginally.
2. **Score ceiling check**: 5/14 F speakers saturate medianResonance ≥ 0.98; F P95 = 1.000.
3. **F-M overlap band**: [0.703, 0.847].
4. Female–male median gap (P50): +0.340.
5. **Sample size warning**: only ~16 speakers total.  Treat conclusions as directional.  For Phase B-style retrain (en @ 5500 Hz), download Common Voice en or LibriSpeech first.