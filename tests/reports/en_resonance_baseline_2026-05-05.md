# en-US resonance baseline (2026-05-05)

**Source**: LibriSpeech train-clean-100 subset at `/mnt/d/project_vocieduck/ablation/audio/en/LibriSpeech` (seed=17, target_f=50, target_m=30, clips_per_spk=3). Transcripts pulled from .trans.txt files (no ASR).  Total clips: 238; speakers: 80.  Per-spk median is the median of that speaker's clip-medians.

Sidecar formant ceiling: pinned 5000 Hz (en NOT in `_ADAPTIVE_LANGS`).  stats.json baseline: cmudict-derived, 5000 Hz extraction (upstream).

**⚠ Small sample**: ~16 unique speakers total — P5/P95 estimates have wide CIs.  Treat as directional, not as a calibration anchor without a larger corpus (CV en, LibriSpeech).


## Table 1 — per-spk median `resonance` distribution

| sex | n_spk | P5 | P25 | P50 | P75 | P95 | mean |
|---|---|---|---|---|---|---|---|
| F | 50 | 0.498 | 0.668 | 0.775 | 0.961 | 1.000 | 0.784 |
| M | 30 | 0.277 | 0.406 | 0.460 | 0.674 | 1.000 | 0.534 |

## Table 2 — per-vowel z-scores (relative to `stats.json`)

ARPABET phones with stress digits stripped (IY1/IY2/IY0 → IY).  Z relative to the female reference distribution in `stats.json`.

### F speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| AH | 1857 | 523 | 1648 | 2807 | +0.42 | +0.35 | +0.58 | 0.51 |
| IH | 1206 | 473 | 1923 | 2798 | +0.29 | +0.31 | +0.61 | 0.49 |
| IY | 713 | 379 | 2297 | 2870 | +0.05 | +0.38 | +0.54 | 0.37 |
| AE | 548 | 737 | 1815 | 2715 | +0.15 | +0.54 | +0.74 | 0.66 |
| ER | 526 | 507 | 1540 | 2073 | +0.10 | +0.51 | +0.10 | 0.41 |
| EH | 508 | 669 | 1834 | 2697 | +0.62 | +0.73 | +0.87 | 0.63 |
| AA | 329 | 781 | 1259 | 2687 | +0.56 | +0.63 | +0.72 | 0.72 |
| AY | 312 | 805 | 1641 | 2683 | +0.03 | +0.88 | +0.72 | 0.53 |
| OW | 266 | 558 | 1221 | 2769 | +0.42 | -0.18 | +0.63 | 0.54 |
| UW | 256 | 405 | 1650 | 2681 | +0.04 | +0.18 | +0.39 | 0.26 |
| EY | 249 | 503 | 2235 | 2802 | +0.20 | +0.53 | +0.50 | 0.50 |
| AO | 141 | 511 | 1007 | 2524 | -0.65 | -0.33 | +0.00 | 0.67 |
| OY | 18 | 550 | 1087 | 2624 | +0.11 | -0.44 | +0.46 | 0.44 |

### M speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| AH | 1128 | 423 | 1428 | 2516 | -0.25 | -0.25 | -0.05 | 0.44 |
| IH | 671 | 393 | 1750 | 2548 | -0.40 | -0.12 | -0.10 | 0.51 |
| IY | 403 | 310 | 2121 | 2605 | -0.63 | +0.01 | -0.39 | 0.43 |
| AE | 319 | 591 | 1662 | 2524 | -0.70 | +0.05 | +0.19 | 0.56 |
| EH | 306 | 524 | 1596 | 2475 | -0.59 | -0.13 | +0.21 | 0.47 |
| ER | 295 | 415 | 1345 | 1960 | -0.70 | -0.25 | -0.19 | 0.64 |
| AY | 200 | 656 | 1435 | 2437 | -0.99 | -0.05 | +0.08 | 0.70 |
| AA | 197 | 632 | 1097 | 2463 | -0.48 | -0.29 | +0.19 | 0.47 |
| EY | 178 | 412 | 2000 | 2576 | -0.66 | -0.05 | -0.30 | 0.52 |
| UW | 151 | 330 | 1377 | 2355 | -0.51 | -0.57 | -0.52 | 0.58 |
| OW | 138 | 456 | 1006 | 2542 | -0.57 | -0.79 | +0.06 | 0.69 |
| AO | 104 | 462 | 885 | 2329 | -0.96 | -0.83 | -0.43 | 0.74 |
| OY | 11 | 485 | 1045 | 2414 | -0.55 | -0.59 | -0.15 | 0.60 |

## Table 3 — F2 collapse check (female speakers vs Hillenbrand 1995)

| vowel | n | F2_med (this run) | F2 lit | ratio | verdict |
|---|---|---|---|---|---|
| IY | 610 | 2297 | 2960 | 0.78 | low |
| IH | 1179 | 1923 | 2350 | 0.82 | low |
| EH | 506 | 1834 | 2190 | 0.84 | low |
| EY | 235 | 2235 | 2350 | 0.95 | ok |
| AE | 549 | 1815 | 2050 | 0.89 | ok |
| AH | 1826 | 1648 | 1545 | 1.07 | ok |
| AA | 325 | 1259 | 1130 | 1.11 | ok |
| AO | 104 | 1007 | 840 | 1.20 | ok |
| OW | 250 | 1221 | 960 | 1.27 | ok |
| UH | 0 | — | 1120 | — | n<5 |
| UW | 253 | 1650 | 1100 | 1.50 | ok |
| AW | 0 | — | 1290 | — | n<5 |
| AY | 313 | 1641 | 1700 | 0.97 | ok |
| OY | 18 | 1087 | 1100 | 0.99 | ok |
| ER | 523 | 1540 | 1590 | 0.97 | ok |

## Table 4 — 5-zone candidate thresholds (en F percentiles)

| zone_key | range |
|---|---|
| `clearly_male` | < 0.498 |
| `leans_male` | [0.498, 0.668) |
| `neutral` | [0.668, 0.961) |
| `leans_female` | [0.961, 1.0) |
| `clearly_female` | ≥ 1.0 |

## Decision points

1. **F2 soft-low** on /IY, /IH, /EH/ — below Hillenbrand but >75 %.  Adding en to adaptive ceiling would help marginally.
2. **Score ceiling check**: 12/50 F speakers saturate medianResonance ≥ 0.98; F P95 = 1.000.
3. **F-M overlap band**: [0.498, 1.000].
4. Female–male median gap (P50): +0.315.
5. **Sample size warning**: only ~16 speakers total.  Treat conclusions as directional.  For Phase B-style retrain (en @ 5500 Hz), download Common Voice en or LibriSpeech first.