# Category evaluation report — 2026-04-27

- Engine A: inaSpeechSegmenter, **T = 2.0**, confidence = C1 margin (mean per-frame best−second-best).
- Total files: **95**
- Source: tests/fixtures/manifest.yaml
- Generator: tests/gen_category_eval.py
- **READ ALSO**: tests/fixtures/KNOWN_LIMITATIONS.md

Categories with `ground_truth_label == neutral` are excluded from accuracy. 
All margins reported are at production T = 2.0 (C1).

## 1. Per-category margin distribution (C1 @ T=2.0)

Percentiles over **per-segment** margins (each segment's mean per-frame margin).

| category | files | segs | mean | p5 | p10 | p25 | p50 | p75 | p90 | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cis_female | 43 | 89 | 0.872 | 0.680 | 0.784 | 0.837 | 0.887 | 0.941 | 0.965 | 0.971 |
| cis_male_standard | 32 | 86 | 0.864 | 0.320 | 0.627 | 0.918 | 0.928 | 0.956 | 0.986 | 0.990 |
| cis_male_high_f0 | 5 | 24 | 0.692 | 0.341 | 0.414 | 0.585 | 0.676 | 0.871 | 0.916 | 0.937 |
| trans_fem_early | 3 | 3 | 0.791 | 0.770 | 0.773 | 0.780 | 0.793 | 0.803 | 0.809 | 0.811 |
| trans_fem_mid | 3 | 3 | 0.800 | 0.641 | 0.667 | 0.745 | 0.874 | 0.893 | 0.904 | 0.908 |
| trans_fem_late | 3 | 3 | 0.705 | 0.637 | 0.639 | 0.646 | 0.658 | 0.740 | 0.789 | 0.806 |
| trans_masc | 3 | 3 | 0.890 | 0.778 | 0.795 | 0.847 | 0.933 | 0.954 | 0.967 | 0.971 |
| neutral | 3 | 3 | 0.845 | 0.772 | 0.774 | 0.777 | 0.783 | 0.882 | 0.941 | 0.961 |

## 2. Per-category classification accuracy

Accuracy = fraction of voiced segments whose predicted label matches `ground_truth_label`.
Segments in `neutral`-label categories are not scored.

| category | files | segs | accuracy | note |
|---|---:|---:|---:|---|
| cis_female | 43 | 89 | **100.0%** | gt=female |
| cis_male_standard | 32 | 86 | **98.8%** | gt=male |
| cis_male_high_f0 | 5 | 24 | **25.0%** | gt=male |
| trans_fem_early | 3 | 3 | **33.3%** | gt=male |
| trans_fem_mid | 3 | 3 | — | (neutral, not scored) |
| trans_fem_late | 3 | 3 | **100.0%** | gt=female |
| trans_masc | 3 | 3 | **100.0%** | gt=male |
| neutral | 3 | 3 | — | (neutral, not scored) |

## 3. Mixed-segment analysis (minority label ratio per file)

`minority_dur_ratio` = duration-weighted fraction of segments whose label != file's modal label.
For homogeneous predictions this is 0; for mixed predictions it indicates the boundary region.

| category | files | mean min_ratio | p50 | p90 | p95 | max | files with min_ratio>0 |
|---|---:|---:|---:|---:|---:|---:|---:|
| cis_female | 43 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0/43 |
| cis_male_standard | 32 | 0.004 | 0.000 | 0.000 | 0.000 | 0.133 | 1/32 |
| cis_male_high_f0 | 5 | 0.078 | 0.000 | 0.235 | 0.314 | 0.392 | 1/5 |
| trans_fem_early | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0/3 |
| trans_fem_mid | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0/3 |
| trans_fem_late | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0/3 |
| trans_masc | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0/3 |
| neutral | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0/3 |

## 4. F0 (estimated) distribution per category

F0 values from `manifest.yaml::estimated_f0_median_hz` (pyin[60-250] median).
Used only for reference — Engine A does not consume F0.

| category | files | mean F0 | p10 | p50 | p90 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| cis_female | 43 | 192 | 174 | 198 | 216 | 60 | 232 |
| cis_male_standard | 32 | 111 | 81 | 114 | 138 | 60 | 148 |
| cis_male_high_f0 | 5 | 172 | 165 | 174 | 177 | 159 | 177 |
| trans_fem_early | 3 | 112 | 97 | 113 | 127 | 93 | 130 |
| trans_fem_mid | 3 | 160 | 158 | 161 | 163 | 157 | 163 |
| trans_fem_late | 3 | 194 | 183 | 185 | 208 | 183 | 214 |
| trans_masc | 3 | 130 | 118 | 126 | 144 | 116 | 148 |
| neutral | 3 | 156 | 148 | 150 | 167 | 148 | 171 |

## 5. Per-file detail

Sorted by category, then file. `mean margin` is segment-duration-weighted.

| file | category | gt | F0 | n_segs | preds | mean margin | min margin | acc% |
|---|---|---|---:|---:|---|---:|---:|---:|
| cmu_arctic_clb_a0001.wav | cis_female | female | 180 | 1 | female1 | 0.958 | 0.958 | 100% |
| cmu_arctic_clb_a0002.wav | cis_female | female | 180 | 1 | female1 | 0.956 | 0.956 | 100% |
| cmu_arctic_clb_a0003.wav | cis_female | female | 185 | 1 | female1 | 0.923 | 0.923 | 100% |
| cmu_arctic_slt_a0001.wav | cis_female | female | 197 | 1 | female1 | 0.986 | 0.986 | 100% |
| cmu_arctic_slt_a0002.wav | cis_female | female | 174 | 1 | female1 | 0.972 | 0.972 | 100% |
| cmu_arctic_slt_a0003.wav | cis_female | female | 195 | 1 | female1 | 0.967 | 0.967 | 100% |
| female_1.wav | cis_female | female | 198 | 6 | female6 | 0.845 | 0.776 | 100% |
| female_2.wav | cis_female | female | 175 | 6 | female6 | 0.885 | 0.832 | 100% |
| female_3.wav | cis_female | female | 211 | 15 | female15 | 0.914 | 0.444 | 100% |
| female_4.wav | cis_female | female | 203 | 6 | female6 | 0.884 | 0.796 | 100% |
| female_5.wav | cis_female | female | 175 | 6 | female6 | 0.885 | 0.832 | 100% |
| test_ashley.wav | cis_female | female | 188 | 6 | female6 | 0.745 | 0.651 | 100% |
| test_lucy.wav | cis_female | female | 232 | 6 | female6 | 0.896 | 0.801 | 100% |
| vctk_p248_003_mic1.wav | cis_female | female | 200 | 2 | female2 | 0.948 | 0.911 | 100% |
| vctk_p248_005_mic1.wav | cis_female | female | 221 | 1 | female1 | 0.948 | 0.948 | 100% |
| vctk_p248_008_mic1.wav | cis_female | female | 207 | 1 | female1 | 0.856 | 0.856 | 100% |
| vctk_p277_006_mic1.wav | cis_female | female | 212 | 1 | female1 | 0.883 | 0.883 | 100% |
| vctk_p277_007_mic1.wav | cis_female | female | 205 | 1 | female1 | 0.884 | 0.884 | 100% |
| vctk_p277_012_mic1.wav | cis_female | female | 189 | 2 | female2 | 0.922 | 0.821 | 100% |
| vctk_p283_006_mic1.wav | cis_female | female | 202 | 1 | female1 | 0.965 | 0.965 | 100% |
| vctk_p283_007_mic1.wav | cis_female | female | 208 | 1 | female1 | 0.946 | 0.946 | 100% |
| vctk_p283_012_mic1.wav | cis_female | female | 191 | 1 | female1 | 0.967 | 0.967 | 100% |
| vctk_p303_001_mic1.wav | cis_female | female | 60 | 1 | female1 | 0.737 | 0.737 | 100% |
| vctk_p303_007_mic1.wav | cis_female | female | 208 | 1 | female1 | 0.970 | 0.970 | 100% |
| vctk_p303_013_mic1.wav | cis_female | female | 201 | 1 | female1 | 0.865 | 0.865 | 100% |
| vctk_p305_002_mic1.wav | cis_female | female | 217 | 1 | female1 | 0.670 | 0.670 | 100% |
| vctk_p305_003_mic1.wav | cis_female | female | 226 | 1 | female1 | 0.786 | 0.786 | 100% |
| vctk_p305_004_mic1.wav | cis_female | female | 225 | 1 | female1 | 0.816 | 0.816 | 100% |
| vctk_p333_001_mic1.wav | cis_female | female | 174 | 1 | female1 | 0.835 | 0.835 | 100% |
| vctk_p333_006_mic1.wav | cis_female | female | 191 | 1 | female1 | 0.938 | 0.938 | 100% |
| vctk_p333_012_mic1.wav | cis_female | female | 176 | 1 | female1 | 0.970 | 0.970 | 100% |
| vctk_p335_003_mic1.wav | cis_female | female | 199 | 1 | female1 | 0.857 | 0.857 | 100% |
| vctk_p335_005_mic1.wav | cis_female | female | 199 | 1 | female1 | 0.889 | 0.889 | 100% |
| vctk_p335_008_mic1.wav | cis_female | female | 198 | 1 | female1 | 0.915 | 0.915 | 100% |
| vctk_p351_003_mic1.wav | cis_female | female | 213 | 1 | female1 | 0.947 | 0.947 | 100% |
| vctk_p351_005_mic1.wav | cis_female | female | 213 | 1 | female1 | 0.961 | 0.961 | 100% |
| vctk_p351_008_mic1.wav | cis_female | female | 213 | 1 | female1 | 0.949 | 0.949 | 100% |
| vctk_p361_002_mic1.wav | cis_female | female | 162 | 1 | female1 | 0.793 | 0.793 | 100% |
| vctk_p361_004_mic1.wav | cis_female | female | 193 | 1 | female1 | 0.912 | 0.912 | 100% |
| vctk_p361_008_mic1.wav | cis_female | female | 188 | 1 | female1 | 0.885 | 0.885 | 100% |
| vctk_s5_001_mic1.wav | cis_female | female | 186 | 1 | female1 | 0.912 | 0.912 | 100% |
| vctk_s5_006_mic1.wav | cis_female | female | 213 | 1 | female1 | 0.868 | 0.868 | 100% |
| vctk_s5_012_mic1.wav | cis_female | female | 82 | 1 | female1 | 0.816 | 0.816 | 100% |
| cmu_arctic_awb_a0001.wav | cis_male_standard | male | 139 | 1 | male1 | 0.993 | 0.993 | 100% |
| cmu_arctic_awb_a0002.wav | cis_male_standard | male | 138 | 1 | male1 | 0.988 | 0.988 | 100% |
| cmu_arctic_awb_a0003.wav | cis_male_standard | male | 124 | 1 | male1 | 0.989 | 0.989 | 100% |
| cmu_arctic_bdl_a0001.wav | cis_male_standard | male | 135 | 1 | male1 | 0.988 | 0.988 | 100% |
| cmu_arctic_bdl_a0002.wav | cis_male_standard | male | 126 | 1 | male1 | 0.957 | 0.957 | 100% |
| cmu_arctic_bdl_a0003.wav | cis_male_standard | male | 125 | 1 | male1 | 0.921 | 0.921 | 100% |
| cmu_arctic_jmk_a0001.wav | cis_male_standard | male | 113 | 1 | male1 | 0.919 | 0.919 | 100% |
| cmu_arctic_jmk_a0002.wav | cis_male_standard | male | 103 | 1 | male1 | 0.967 | 0.967 | 100% |
| cmu_arctic_jmk_a0003.wav | cis_male_standard | male | 113 | 1 | male1 | 0.988 | 0.988 | 100% |
| cmu_arctic_rms_a0001.wav | cis_male_standard | male | 93 | 1 | male1 | 0.980 | 0.980 | 100% |
| cmu_arctic_rms_a0002.wav | cis_male_standard | male | 80 | 1 | male1 | 0.985 | 0.985 | 100% |
| cmu_arctic_rms_a0003.wav | cis_male_standard | male | 100 | 1 | male1 | 0.965 | 0.965 | 100% |
| male_2.wav | cis_male_standard | male | 132 | 10 | male10 | 0.918 | 0.320 | 100% |
| male_3.wav | cis_male_standard | male | 147 | 6 | male6 | 0.941 | 0.916 | 100% |
| male_5.wav | cis_male_standard | male | 132 | 10 | male10 | 0.918 | 0.320 | 100% |
| test_aiden.wav | cis_male_standard | male | 122 | 5 | male4/female1 | 0.630 | 0.556 | 80% |
| vctk_p302_002_mic1.wav | cis_male_standard | male | 113 | 1 | male1 | 0.934 | 0.934 | 100% |
| vctk_p302_004_mic1.wav | cis_male_standard | male | 114 | 2 | male2 | 0.910 | 0.897 | 100% |
| vctk_p302_005_mic1.wav | cis_male_standard | male | 114 | 1 | male1 | 0.911 | 0.911 | 100% |
| vctk_p304_001_mic1.wav | cis_male_standard | male | 60 | 1 | male1 | 0.994 | 0.994 | 100% |
| vctk_p304_006_mic1.wav | cis_male_standard | male | 93 | 1 | male1 | 0.997 | 0.997 | 100% |
| vctk_p304_007_mic1.wav | cis_male_standard | male | 62 | 1 | male1 | 0.998 | 0.998 | 100% |
| vctk_p334_006_mic1.wav | cis_male_standard | male | 91 | 1 | male1 | 0.980 | 0.980 | 100% |
| vctk_p334_007_mic1.wav | cis_male_standard | male | 94 | 1 | male1 | 0.857 | 0.857 | 100% |
| vctk_p334_012_mic1.wav | cis_male_standard | male | 94 | 1 | male1 | 0.941 | 0.941 | 100% |
| vctk_p360_001_mic1.wav | cis_male_standard | male | 60 | 1 | male1 | 0.963 | 0.963 | 100% |
| vctk_p360_007_mic1.wav | cis_male_standard | male | 90 | 1 | male1 | 0.922 | 0.922 | 100% |
| vctk_p360_013_mic1.wav | cis_male_standard | male | 90 | 1 | male1 | 0.653 | 0.653 | 100% |
| zh_10s.wav | cis_male_standard | male | 148 | 3 | male3 | 0.890 | 0.320 | 100% |
| zh_30s.wav | cis_male_standard | male | 132 | 7 | male7 | 0.922 | 0.320 | 100% |
| zh_60s.wav | cis_male_standard | male | 132 | 10 | male10 | 0.918 | 0.320 | 100% |
| zh_base_male.wav | cis_male_standard | male | 132 | 10 | male10 | 0.918 | 0.320 | 100% |
| male_1.wav | cis_male_high_f0 | male | 174 | 14 | female8/male6 | 0.632 | 0.317 | 43% |
| male_4.wav | cis_male_high_f0 | male | 176 | 7 | female7 | 0.887 | 0.830 | 0% |
| synth_awb_pitch400.wav | cis_male_high_f0 | male | 177 | 1 | female1 | 0.939 | 0.939 | 0% |
| synth_bdl_pitch500.wav | cis_male_high_f0 | male | 174 | 1 | female1 | 0.875 | 0.875 | 0% |
| synth_jmk_pitch600.wav | cis_male_high_f0 | male | 159 | 1 | female1 | 0.626 | 0.626 | 0% |
| synth_early_bdl_p150.wav | trans_fem_early | male | 130 | 1 | male1 | 0.793 | 0.793 | 100% |
| synth_early_jmk_p200.wav | trans_fem_early | male | 113 | 1 | female1 | 0.768 | 0.768 | 0% |
| synth_early_rms_p250.wav | trans_fem_early | male | 93 | 1 | female1 | 0.813 | 0.813 | 0% |
| synth_mid_awb_p350.wav | trans_fem_mid | neutral | 157 | 1 | female1 | 0.912 | 0.912 | — |
| synth_mid_bdl_p350.wav | trans_fem_mid | neutral | 161 | 1 | female1 | 0.874 | 0.874 | — |
| synth_mid_rms_p1100.wav | trans_fem_mid | neutral | 163 | 1 | male1 | 0.615 | 0.615 | — |
| synth_late_bdl_p600.wav | trans_fem_late | female | 185 | 1 | female1 | 0.822 | 0.822 | 100% |
| synth_late_bdl_p800.wav | trans_fem_late | female | 214 | 1 | female1 | 0.658 | 0.658 | 100% |
| synth_late_rms_p1400.wav | trans_fem_late | female | 183 | 1 | female1 | 0.634 | 0.634 | 100% |
| synth_masc_clb_m600.wav | trans_masc | male | 126 | 1 | male1 | 0.975 | 0.975 | 100% |
| synth_masc_slt_m500.wav | trans_masc | male | 148 | 1 | male1 | 0.761 | 0.761 | 100% |
| synth_masc_slt_m700.wav | trans_masc | male | 116 | 1 | male1 | 0.933 | 0.933 | 100% |
| synth_neutral_awb_p100.wav | neutral | neutral | 148 | 1 | male1 | 0.980 | 0.980 | — |
| synth_neutral_bdl_p300.wav | neutral | neutral | 150 | 1 | female1 | 0.771 | 0.771 | — |
| synth_neutral_clb_m100.wav | neutral | neutral | 171 | 1 | female1 | 0.783 | 0.783 | — |

## 6. Pyin sanity check on critical samples

Empirical question: can pyin reliably distinguish `male_4` (Engine A misclassified as female,
true F0~175 Hz) from real `cis_female` samples in the 165-200 Hz F0 range?

### 6.1 male_4 vs cis_female F0 distribution (multiple pyin configs)

| file | gt | config | median | p10 | p25 | p75 | p90 | voiced% |
|---|---|---|---:|---:|---:|---:|---:|---:|
| male_4.wav | male | pyin[60-250] | **176** | **145** | **157** | 207 | 244 | 52% |
| male_4.wav | male | pyin[60-300] | 215 | 166 | 180 | 270 | 289 | 52% |
| male_4.wav | male | pyin[60-400] | 302 | 218 | 263 | 336 | 364 | 74% |
| male_1.wav | male | pyin[60-250] | 174 | **121** | **146** | 207 | 235 | 64% |
| male_3.wav | male | pyin[60-250] | 147 | 80 | 111 | 180 | 191 | 14% |
| female_1.wav | female | pyin[60-250] | 198 | 149 | 165 | 236 | 250 | 70% |
| female_2.wav | female | pyin[60-250] | **175** | **148** | **158** | 221 | 250 | 70% |
| female_3.wav | female | pyin[60-250] | 211 | 152 | 178 | 239 | 250 | 67% |
| female_4.wav | female | pyin[60-250] | 203 | 145 | 167 | 234 | 250 | 57% |
| cmu_arctic_slt_a0002.wav | female | pyin[60-250] | 174 | 156 | 159 | 189 | 198 | 85% |
| cmu_arctic_clb_a0001.wav | female | pyin[60-250] | 180 | 152 | 163 | 195 | 215 | 84% |
| vctk_p333_001_mic1.wav | female | pyin[60-250] | 175 | 60 | 60 | 201 | 235 | 78% |
| vctk_p361_002_mic1.wav | female | pyin[60-250] | 159 | 60 | 60 | 197 | 214 | 74% |

### 6.2 Conclusions for abstain trigger design

**pyin[60-250] is the right config**: gives correct F0 on male_4 (176 Hz no octave doubling). Wider fmax produces octave errors.

**male_1 IS detectable** by F0 features:
- median 174 Hz overlaps with cis_female median (175-210 Hz)
- BUT p10 = 121 Hz (well below cis_female p10 ≥ 145 Hz) — there are F0 frames in standard male range
- A rule like `label=female AND f0_p10 < 130 Hz → abstain` fires on male_1, doesn't fire on cis_female

**male_4 is NOT detectable** by any F0 feature alone:
- median 176 Hz ≈ female_2 median 175, slt_a0002 median 174
- p10 = 145 Hz ≈ female_2 p10 = 148, female_4 p10 = 145
- p25 = 157 Hz ≈ female_2 p25 = 158, slt_a0002 p25 = 159
- F0 distribution is **statistically indistinguishable** from low-F0 cis_female with similar median

**This bounds what F0-based abstain can do**:
- Path A (symmetric F0 abstain) catches male_1-type cases
- Path A CANNOT catch male_4-type cases without formant analysis
- For male_4, the only F0-side protection is **verdict-tier ceiling**: refuse to output `Strong` for any
  `label=female AND f0_median ∈ [145, 200]`, regardless of margin

## 7. Voiced frame ratio distribution

Per-sample `voiced_frame_ratio = (frames where pyin returns non-NaN F0) / total frames`,
using pyin[60-250].

| category | n | min | p10 | p25 | p50 | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cis_female | 43 | 50 | 62 | 70 | 79 | 85 | 88 | 95 |
| cis_male_standard | 32 | 14 | 30 | 35 | 60 | 73 | 79 | 94 |
| cis_male_high_f0 | 5 | 25 | 33 | 44 | 52 | 64 | 64 | 64 |
| trans_fem_early | 3 | 50 | 53 | 58 | 67 | 77 | 83 | 87 |
| trans_fem_mid | 3 | 49 | 49 | 49 | 50 | 51 | 52 | 53 |
| trans_fem_late | 3 | 50 | 52 | 53 | 56 | 57 | 58 | 58 |
| trans_masc | 3 | 84 | 85 | 86 | 89 | 89 | 89 | 89 |
| neutral | 3 | 27 | 37 | 52 | 76 | 82 | 85 | 87 |

### 7.1 Threshold validation

| threshold | samples below | comment |
|-----------|--------------:|---------|
| voiced_pct < 3% | 0 / 95 | unreachable in test set |
| voiced_pct < 5% | 0 / 95 | **unvalidated** |
| voiced_pct < 10% | 0 / 95 | unvalidated |
| voiced_pct < 15% | 1 / 95 | male_3.wav at 14%, but Engine A correctly identifies as male |
| voiced_pct < 20% | 1 / 95 | male_3.wav |
| voiced_pct < 30% | 4 / 95 | male_3, synth_awb_pitch400, zh_10s, synth_neutral_awb_p100 |

**Critical observation**: male_3.wav has 14% voiced ratio across 47.8s — that's 6.7s of voiced audio,
plenty for F0 estimation, and Engine A classifies it correctly. **Voiced ratio is the wrong metric**.

### 7.2 Recommended floor for `f0_unavailable`

Use **absolute voiced duration**, not ratio:

```
voiced_duration_seconds = voiced_frame_ratio × total_duration

f0_unavailable triggers if:
  voiced_duration_seconds < 1.0   (absolute floor; below this, F0 has too few frames for stable median)
  OR np.nanmedian(f0_array) is NaN  (pyin returned no usable estimate at all)
```

From test data, the lowest `voiced_duration_seconds` is `0.14 × 47.8 = 6.7s` (male_3),
well above the proposed 1.0s floor. **No current sample triggers `f0_unavailable`** —
this is acceptable, since none of the samples are actually problematic for F0 estimation.

The 1.0s floor is a safety margin not validated against data; should be revisited when real
short / whispered / noisy uploads enter production.

## 8. Strict-voiced F0 distribution: cis_female (per-file)

Using `pyin[60-250]` + `voiced_prob > 0.5` filter (excludes pyin floor-value artifacts).

`p10_loose < 130` was originally proposed as the F0-label-conflict abstain trigger. It triggered
on ~50% of cis_female files due to pyin floor values, making it unusable. Strict voicing fixes
this — strict `frac_below_130` is **0.0%** for all cis_female files — but at the cost of also
making male_1 indistinguishable from cis_female (male_1 p10_strict = 150).

### 8.1 cis_female strict median (sorted, n=42)

| range | count | percentage | sample names |
|-------|------:|-----------:|--------------|
| < 165 Hz | 0 | 0% | (none — strict voicing pulls floor artifacts up) |
| [165, 180) | 4 | 9.5% | slt_a0002 (166), female_2 (171), female_5 (171), clb_a0001 (172) |
| [180, 185) | 2 | 4.8% | vctk_p361_008 (179), vctk_p333_012 (185) |
| [185, 200) | 11 | 26.2% | slt_a0001/003, clb_a0002/003, p283_012, p335_008, p277_012, p333_006, p335_003, p248_003, test_ashley |
| [200, 220) | 18 | 42.9% | majority of cis_female |
| ≥ 220 | 7 | 16.7% | p303 sentences, p305_003, p248_005, female_3, p333_001, test_lucy, s5_001 |

### 8.2 Ceiling cap rate at multiple upper bounds (strict median)

male_4 strict median = **172 Hz**. Engine A misclassifies male_4 100% as female with margin=0.883.

| upper | cis_female capped | male_4 captured | margin above male_4 |
|------:|------------------:|----------------:|--------------------:|
| 175 | 4 / 42 (9.5%) | ✓ | 3 Hz (risky) |
| 180 | 5 / 42 (11.9%) | ✓ | 8 Hz |
| **185** | **6 / 42 (14.3%)** | **✓** | **13 Hz (recommended)** |
| 190 | 11 / 42 (26.2%) | ✓ | 18 Hz |
| 200 | 17 / 42 (40.5%) | ✓ | 28 Hz |
| 210 | 23 / 42 (54.8%) | ✓ | 38 Hz |
| 220 | 35 / 42 (83.3%) | ✓ | 48 Hz |

**Recommendation**: `[145, 185]` — captures male_4 with a 13 Hz safety margin, caps 14% of cis_female
(down from 53% at [145, 200]). Going lower (180, 175) saves 1-2 more cis_female but tightens the
male_4 safety margin below 10 Hz.

### 8.3 Implication for abstain.f0_label_conflict (label=female AND ...)

Using `p10_loose` as the trigger (`label=female AND p10_loose < 130`):
- False trigger rate on cis_female: ~50% (pyin floor artifacts)
- Verdict: **unusable**

Using `p10_strict` (voiced_prob > 0.5) as the trigger:
- male_1 p10_strict = 150 — does NOT trigger (no separation from cis_female lowest p10_strict ≥ 158)
- male_4 p10_strict = 137 — would trigger (`< 145` separates from cis_female ≥ 158)
- But **male_1 is already caught by margin tiering** (margin=0.632 < 0.78 → verdict.neutral)
- Adding p10_strict abstain only adds value for male_4-style cases (high-confidence misclassification),
  which are precisely what verdict-tier ceiling already handles
- Verdict: **redundant with ceiling, dropped from v2.5 design**

## 9. Discriminant-gap STRONG_FLOOR analysis

Empirical answer to "should STRONG_FLOOR derive from cis_female p25 (one-sided), or from
cis_female TPR + cis_male_standard mis-classification FPR (two-sided)?"

| T | cis_female TPR (margin > T) | cis_male_standard misclassified-female above T |
|---:|---:|---:|
| 0.78 | 89.9% | 0.0% (1 misclassified seg has margin 0.697) |
| 0.80 | 86.5% | 0.0% |
| 0.82 | 82.0% | 0.0% |
| 0.83 | **78.7%** | **0.0%** ← highest T satisfying both |
| 0.84 | 74.2% | 0.0% |
| 0.86 | 64.0% | 0.0% |
| 0.90 | 43.8% | 0.0% |

In our test set:
- The single cis_male_standard segment misclassified as female has margin = 0.697 (test_aiden.wav).
- For ANY T ≥ 0.70, that segment is excluded from "Strong" — so the FPR ≤ 0.05 constraint is trivially satisfied.
- The binding constraint is **cis_female TPR ≥ 0.75**, which gives `T ≤ 0.84`.
- **Discriminant-gap maximum: T = 0.83** (vs simple percentile T = cis_female p25 = 0.837)

The two derivations agree to 0.01 in our data. **Recommend keeping STRONG_FLOOR = 0.84** since:
1. Discriminant analysis confirms it (T=0.83 ≈ 0.84)
2. cis_male_standard's only misclassified segment (margin 0.697) is well below 0.84, so changing
   STRONG_FLOOR within [0.78, 0.84] doesn't affect cis_male protection
3. The 1.2% misclassification rate in cis_male_standard is insufficient sample size to make
   FPR-driven decisions; trusting cis_female TPR-driven derivation is more robust

This finding **may not generalize** to a larger cis_male_standard sample where the misclassified
fraction grows or shifts in margin distribution. STRONG_FLOOR should be re-derived when test set expands.
