# E2E perturbation report — 2026-05-05

## Setup
- API: `http://localhost:8080`
- Sidecar health: `http://localhost:8001/healthz`
- F0 perturbation: ±4 semitones
- Formant factor: V3=×1.2, V4=×0.833
- Min duration after pad: 12.0 s

## Per-language results

### zh-CN — `tests/fixtures/audio/zh_30s.wav`
_duration after pad: 30.0 s_

| Variant | F0 Hz | gender | median_res | weakness | sample per_vowel |
|---------|------:|-------:|-----------:|---------:|------------------|
| V0 baseline | 132 | 3.1 | 0.403 | 3 | /i/=0.00(weak), /o/=0.00(weak), /a/=0.00(weak), /y/=0.00(weak) |
| V0p baseline rerun | 132 | 3.1 | 0.405 | 3 | /i/=0.00(weak), /o/=0.00(weak), /a/=0.00(weak), /y/=0.00(weak) |
| V1 F0 +4 semi | 183 | 74.8 | 0.723 | 3 | /ow/=0.08(weak), /aj/=0.16(weak), /o/=0.27(weak), /y/=0.38(weak) |
| V2 F0 -4 semi | 100 | 1.4 | 1.0 | 0 | /e/=0.45(low), /a/=0.66(good), /u/=0.90(good), /o/=1.00(good) |
| V3 formants ×1.2 | 173 | 74.4 | 0.703 | 2 | /o/=0.26(weak), /a/=0.37(weak), /ow/=0.44(low), /i/=0.56(low) |
| V4 formants ×0.83 | 141 | 0.6 | 0.419 | 3 | /i/=0.00(weak), /o/=0.00(weak), /ə/=0.00(weak), /a/=0.00(weak) |

### en-US — `tests/fixtures/audio/cis_female/vctk_p248_003_mic1.wav`
_duration after pad: 19.1 s_

| Variant | F0 Hz | gender | median_res | weakness | sample per_vowel |
|---------|------:|-------:|-----------:|---------:|------------------|
| V0 baseline | 196 | 98.9 | 0.956 | 0 | /AH/=1.00(good), /IY/=1.00(good), /AE/=1.00(good), /ER/=1.00(good) |
| V0p baseline rerun | 196 | 98.9 | 0.956 | 0 | /AH/=1.00(good), /IY/=1.00(good), /AE/=1.00(good), /ER/=1.00(good) |
| V1 F0 +4 semi | 246 | 64.2 | 0.985 | 0 | /IY/=0.57(low), /AH/=1.00(good), /AE/=1.00(good) |
| V2 F0 -4 semi | 160 | 10.1 | 0.402 | 1 | /IY/=0.14(weak), /AH/=0.42(low), /AE/=0.92(good) |
| V3 formants ×1.2 | 234 | 66.0 | 0.92 | 0 | /AH/=1.00(good), /IY/=1.00(good) |
| V4 formants ×0.83 | 166 | 33.9 | 0.477 | 0 | /AH/=0.51(low), /AE/=0.97(good) |

### fr-FR — _(no fixture)_
_skipped: no fixture_

## Assertions

- **PASS** `schema/per_vowel_present`
- **PASS** `schema/resonance_med_in_range`
- **PASS** `schema/no_legacy_F_axis_fields`
- **PASS** `schema/level_key_in_set`
- **PASS** `determinism/zh-CN` — |Δf0|=0.00Hz  |Δmedian_res|=0.0020
- **PASS** `determinism/en-US` — |Δf0|=0.00Hz  |Δmedian_res|=0.0000
- **PASS** `f0_only/direction.zh-CN` — V1=183 V0=132 V2=100
- **PASS** `f0_only/direction.en-US` — V1=246 V0=196 V2=160
- **PASS** `formant/direction.zh-CN` — V3=0.703 > V4=0.419
- **PASS** `formant/direction.en-US` — V3=0.92 > V4=0.477
- **PASS** `formant/amplitude.zh-CN` — V3-V4=0.284 (need ≥ 0.05)
- **PASS** `formant/amplitude.en-US` — V3-V4=0.443 (need ≥ 0.05)
- **PASS** `lang/zh_uses_ipa_alphabet` — vowels=ioayajowawʐ̩ueə
- **PASS** `lang/en_uses_arpabet_alphabet` — vowels=AHIYAEER
- **PASS** `weakness/uses_resonance_low_key` — text_keys observed: ['advice.resonance.weakness.resonance_low']

## Verdict

15/15 PASS, 0 FAIL.
