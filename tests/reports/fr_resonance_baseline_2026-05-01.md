# fr-FR resonance baseline (2026-05-01)

**Source**: Common Voice fr v17 train (subset staged at `/home/yaya/scratch/cv_fr_ext4`), sampled 50F + 50M speakers, 5 clips/spk concatenated, seed=17.

Sidecar formant ceiling: adaptive (fr in `_ADAPTIVE_LANGS`).  stats_fr.json baseline: see `voiceya/sidecars/visualizer-backend/stats_fr.json`.

Speakers analyzed: 100 (50F / 50M).  Dropped: 0.


## Table 1 — per-spk median `resonance` distribution

| sex | n | P5 | P25 | P50 | P75 | P95 | mean |
|---|---|---|---|---|---|---|---|
| F | 50 | 0.420 | 0.580 | 0.669 | 0.795 | 0.943 | 0.679 |
| M | 50 | 0.185 | 0.279 | 0.327 | 0.421 | 0.597 | 0.363 |

## Table 1b — adaptive-ceiling pick distribution

| ceiling Hz | n speakers |
|---|---|
| 4500 | 27 |
| 5000 | 31 |
| 5500 | 31 |
| 6000 | 8 |
| 6500 | 3 |

## Table 2 — per-vowel z-scores (relative to `stats_fr.json`)

Z is computed against the reference distribution in `stats_fr.json`. Negative ⇒ measurement falls below the reference mean (more male-like in F1/F2 space).  `sat_rate` = fraction of `resonance` values clamped to [0, 0.02] ∪ [0.98, 1].

### F speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| a | 760 | 699 | 1701 | 2834 | +0.51 | +0.71 | +0.97 | 0.60 |
| e | 538 | 420 | 2239 | 3010 | +0.09 | +0.75 | +0.93 | 0.37 |
| i | 522 | 345 | 2371 | 3217 | -0.06 | +0.63 | +0.64 | 0.19 |
| ɛ | 491 | 509 | 2092 | 2930 | +0.24 | +0.74 | +0.96 | 0.48 |
| ɑ̃ | 334 | 620 | 1115 | 2961 | +0.34 | +0.01 | +0.86 | 0.68 |
| ə | 292 | 408 | 1700 | 2810 | -0.07 | +0.43 | +0.62 | 0.20 |
| ɔ | 287 | 489 | 1284 | 2836 | +0.07 | +0.24 | +0.76 | 0.52 |
| ɔ̃ | 213 | 440 | 1167 | 2758 | -0.14 | -0.05 | +0.47 | 0.60 |
| y | 204 | 353 | 2043 | 2804 | -0.13 | +0.45 | +0.63 | 0.18 |
| ɛ̃ | 129 | 640 | 1567 | 2949 | +0.38 | +0.52 | +0.99 | 0.64 |
| u | 122 | 376 | 1177 | 2743 | -0.13 | +0.10 | +0.47 | 0.24 |
| o | 103 | 440 | 1137 | 2856 | +0.22 | +0.18 | +0.69 | 0.47 |
| ø | 93 | 397 | 1725 | 2714 | -0.03 | +0.63 | +0.69 | 0.28 |
| œ | 46 | 566 | 1679 | 2773 | +0.28 | +0.70 | +0.81 | 0.52 |
| ɑ | 18 | 740 | 1490 | 2937 | +0.53 | +0.30 | +0.98 | 0.59 |

### M speakers

| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |
|---|---|---|---|---|---|---|---|---|
| a | 820 | 576 | 1440 | 2436 | -0.31 | -0.13 | -0.01 | 0.45 |
| i | 570 | 291 | 2004 | 2848 | -0.30 | -0.10 | -0.34 | 0.14 |
| e | 530 | 360 | 1881 | 2608 | -0.35 | -0.10 | -0.27 | 0.32 |
| ɛ | 485 | 435 | 1781 | 2533 | -0.31 | -0.06 | -0.20 | 0.40 |
| ɑ̃ | 331 | 539 | 982 | 2396 | -0.10 | -0.36 | -0.11 | 0.55 |
| ɔ | 274 | 428 | 1096 | 2386 | -0.42 | -0.39 | -0.23 | 0.50 |
| ə | 264 | 378 | 1417 | 2440 | -0.27 | -0.41 | -0.37 | 0.28 |
| y | 252 | 296 | 1806 | 2361 | -0.35 | -0.18 | -0.59 | 0.24 |
| ɔ̃ | 204 | 430 | 1130 | 2501 | -0.20 | -0.13 | -0.03 | 0.54 |
| ɛ̃ | 146 | 539 | 1335 | 2421 | -0.15 | -0.18 | -0.03 | 0.44 |
| u | 141 | 330 | 1002 | 2382 | -0.39 | -0.33 | -0.31 | 0.40 |
| o | 130 | 384 | 1031 | 2452 | -0.30 | -0.15 | -0.19 | 0.34 |
| ø | 96 | 355 | 1437 | 2299 | -0.38 | -0.42 | -0.50 | 0.30 |
| œ | 55 | 470 | 1417 | 2436 | -0.45 | -0.22 | -0.09 | 0.51 |
| ɑ | 19 | 598 | 1270 | 2502 | -0.33 | -0.40 | -0.06 | 0.47 |

## Table 3 — F2 collapse check (female speakers vs literature)

Literature targets: Calliope 2002 + Gendrot/Adda-Decker 2007 LREC.  Nasal vowels excluded (nasal coupling lowers F2 by 100-300 Hz unpredictably).

| vowel | n | F2_med (this run) | F2 lit | ratio | verdict |
|---|---|---|---|---|---|
| i | 509 | 2371 | 2700 | 0.88 | ok |
| y | 208 | 2043 | 1900 | 1.08 | ok |
| e | 538 | 2239 | 2400 | 0.93 | ok |
| ɛ | 489 | 2092 | 2000 | 1.05 | ok |
| ə | 291 | 1700 | 1500 | 1.13 | ok |
| ø | 93 | 1725 | 1700 | 1.01 | ok |
| œ | 46 | 1679 | 1600 | 1.05 | ok |
| a | 755 | 1701 | 1500 | 1.13 | ok |
| ɑ | 18 | 1490 | 1200 | 1.24 | ok |
| o | 89 | 1137 | 950 | 1.20 | ok |
| ɔ | 281 | 1284 | 1100 | 1.17 | ok |
| u | 105 | 1177 | 850 | 1.38 | ok |

## Table 4 — 5-zone candidate thresholds for `resonance_zone_key`

Anchored to fr female P5/P25/P75/P95 from Table 1.  `resonance_calibration._ZONES_FR` currently inherits the zh table; this report's numbers are the input for re-anchoring.

| zone_key | range |
|---|---|
| `clearly_male` | < 0.42 |
| `leans_male` | [0.42, 0.58) |
| `neutral` | [0.58, 0.795) |
| `leans_female` | [0.795, 0.943) |
| `clearly_female` | ≥ 0.943 |

## Decision points

1. **F2 collapse not detected** — current pipeline holds for fr.
2. **Score ceiling check**: 1/50 F speakers (2 %) saturate medianResonance ≥ 0.98; F P95 = 0.943.  M P50 = 0.327.  If F saturation > 15 %, the runtime ceiling lift is over-correcting against the 5000-Hz-baseline stats_fr.json — Phase B retrain will compress the F distribution.
3. **F-M overlap band**: [0.420, 0.597].  Inside this band the score isn't sex-discriminative on its own.
4. Female–male median gap (P50): +0.342.  Wide enough for percentile-anchored zones.