"""Resonance score interpretation layer.

The raw ``resonance`` score from the vendored visualizer-backend pipeline
is ``clamp(0, 1, 0.5 + w_F1·z_F1 + w_F2·z_F2 + w_F3·z_F3)`` — a clamped
affine of formant z-scores against a female reference, NOT a probability.
The clamp ranges are tight (≈ ±0.5 σ around female mean) so the score
saturates often: tests/reports/zh_resonance_baseline_2026-05-01.md shows
8 % of cis-female AISHELL-3 speakers hit median ≥ 0.98 even after the
2026-05-01 stats_zh re-train at 5500 Hz Praat ceiling.

This module turns the raw 0-1 number into a discrete 5-tier zone label.
The intent: tell the UI / advice layer "this voice sits at the upper end
of typical female range" rather than a misleading "85 % female".  Tier
boundaries are anchored to female-speaker percentiles measured on a
balanced AISHELL-3 sample (50 F / 42 M, 5 clips per spk, 5500 Hz Praat
ceiling — see tests/reports/zh_resonance_baseline_2026-05-01.md Table 1).

Why F-only anchoring: the raw score is fundamentally a "distance from
female mean" measure (it z-normalises against the female reference
distribution).  Using F percentiles makes the labels self-consistent —
"leans_female" means "above F P50".  M speakers cluster well below F P5
(M P95 = 0.698 vs F P5 = 0.490) so the M side is cleanly partitioned by
the same boundaries.

Pure-function module, no IO.  See ``classify_zone`` for the public API.
"""

from __future__ import annotations

# Female-speaker percentiles on AISHELL-3 train post-Phase-B (5500 Hz Praat
# ceiling, stats_zh.json re-trained 2026-05-01).  Snapshot below — re-running
# scripts/audit_resonance_zh.py on the same fixtures should reproduce these
# within ±0.01 (audit is deterministic seed=17).
#
#   sex  n   P5     P25    P50    P75    P95    mean
#   F    50  0.490  0.612  0.683  0.842  1.000  0.721   ← phase A (2026-05-01, 50 spk)
#   F    94  0.490  0.616  0.726  0.849  1.000  0.734   ← calibration_v1 (2026-05-06, 94 spk)
#   M    42  0.234  0.305  0.403  0.518  0.698  0.417   ← phase A
#   M    94  0.228  0.292  0.382  0.463  0.655  0.396   ← calibration_v1 (multi-session per spk)
#
# Reproducibility: calibration_v1 (tests/reports/calibration_v1/aggregate.csv,
# 94 F + 94 M, 60-90 s sessions) reproduces phase-A within ±0.01 on every
# percentile.  Thresholds below stay at phase-A values — the drift is below
# the reproducibility band, no zone reassignment would result.
#
# The ``leans_female`` upper bound is set to 0.98 (not F P95 = 1.0) so the
# top tier doesn't require whole-recording score saturation — at the clamp
# ceiling the score has lost discriminative power, so we grade-separate the
# saturated cases as a distinct ``at_ceiling`` tier (UX: a hint that "this
# voice has more headroom than the score can express").
#
# Important: ``mid_neutral`` covers F P25-P75 — i.e. **half of real cis
# females sit here**.  i18n copy must reflect that reality (the 2026-05-05
# rewrite removed "still some distance from the female reference"); it's
# the typical female range, not a deficit zone.
_ZH_F_P5 = 0.490
_ZH_F_P25 = 0.612
_ZH_F_P75 = 0.842
_AT_CEILING = 0.98

# Five zones, ordered low → high.  Each entry is (key, upper_bound_exclusive).
# A score x falls in the FIRST zone where x < upper_bound (or the last zone
# if x ≥ all bounds).  ``upper_bound = None`` means "open-ended high tier".
_ZONES_ZH: tuple[tuple[str, float | None], ...] = (
    ("clearly_below_female", _ZH_F_P5),
    ("leans_male", _ZH_F_P25),
    ("mid_neutral", _ZH_F_P75),
    ("leans_female", _AT_CEILING),
    ("at_ceiling", None),
)

# fr-specific anchoring from tests/reports/calibration_v1/aggregate.csv
# (2026-05-06).  90 F + 94 M speakers from Common Voice fr (validated.tsv,
# gender filter, 11 mp3s concatenated to ~60 s session per speaker), sidecar
# adaptive ceiling, stats_fr.json v17-derived.  Snapshot:
#
#   sex  n   P5     P25    P50    P75    P95    mean
#   F    50  0.420  0.580  0.669  0.795  0.943  0.679   ← 2026-05-01 v17 baseline
#   F    90  0.430  0.547  0.646  0.752  0.960  0.659   ← calibration_v1
#   M    50  0.185  0.279  0.327  0.421  0.597  0.363   ← 2026-05-01
#   M    94  0.229  0.294  0.348  0.421  0.601  0.371   ← calibration_v1
#
# Drift from 2026-05-01: F P5 +0.010, P25 -0.033, P75 -0.043, P95 +0.017.
# The bulk of fr distribution shifts DOWN (P25/P50/P75) — the v17 50-spk
# sample over-represented the upper-female tail.  90 spk × 11 stitched
# clips is the better estimate; updating constants below.
#
# Notably still tighter than zh and en: F P95 = 0.960 (≈ 3 % saturation),
# so we use it directly as the ``leans_female`` upper bound instead of
# falling back to the 0.98 clamp ceiling.
_FR_F_P5 = 0.430  # was 0.420
_FR_F_P25 = 0.547  # was 0.580 — meaningful shift down
_FR_F_P75 = 0.752  # was 0.795 — meaningful shift down
_FR_F_P95 = 0.960  # was 0.943

_ZONES_FR: tuple[tuple[str, float | None], ...] = (
    ("clearly_below_female", _FR_F_P5),
    ("leans_male", _FR_F_P25),
    ("mid_neutral", _FR_F_P75),
    ("leans_female", _FR_F_P95),
    ("at_ceiling", None),
)

# en-US percentiles from tests/reports/calibration_v1/aggregate.csv after
# the 2026-05-06 stats.json retrain.  91 F + 92 M speakers from LibriSpeech
# train-clean-100, 6 flacs concatenated to ~60-90 s sessions per speaker,
# sidecar adaptive ceiling 4500–6500 Hz, stats.json re-baked at fixed 5500
# Hz on 5000 LibriSpeech train segments (59 phones).  Snapshot evolution:
#
#   sex  n   P5     P25    P50    P75    P95    mean   src
#   F    50  0.498  0.668  0.775  0.961  1.000  0.784  2026-05-05 (16 spk × 3, upstream stats)
#   F    91  0.525  0.689  0.811  0.987  1.000  0.804  calibration_v1 v0 (upstream stats @ 5000 Hz)
#   F    91  0.351  0.458  0.553  0.682  0.833  0.568  calibration_v1 v1 (re-trained @ 5500 Hz)  ← current
#   M    30  0.277  0.406  0.460  0.674  1.000  0.534  2026-05-05
#   M    92  0.328  0.381  0.489  0.639  1.000  0.546  calibration_v1 v0
#   M    92  0.195  0.237  0.286  0.385  0.673  0.339  calibration_v1 v1  ← current
#
# Why the distribution shifted DOWN despite "fixing" the ceiling: the old
# upstream stats.json had an artificially-depressed /IY1/ F2 mean of
# 2112 Hz (vs literature ~2960) because Praat's 5-pole LPC at 5000 Hz
# intermittently fused F1+F2 into a spurious low-frequency peak when
# female F2 sat near 5000 Hz.  Real F speakers measuring their TRUE F2
# (~2700-2900 Hz) thus scored z = +1.6 to +2.7 above this depressed
# reference and saturated at the clamp ceiling (26 % of F samples hit
# resonance ≥ 0.98).  Re-training at 5500 Hz lifts /IY1/ F2 mean to
# 2353 Hz and tightens stdev (474 → 336), so the same TRUE-F2-2800
# speaker now scores z = +1.0 — high, but no longer saturating.
#
# The cost: the old "F P50 = 0.811" was largely an artifact of the
# downward-biased reference.  Honest reference makes F speakers cluster
# around their own population mean at z ≈ 0 → resonance ≈ 0.5–0.55.
# This is the algorithmic intent (``0.5 = female reference mean``) finally
# being expressed accurately.  See voiceya/sidecars/visualizer-backend/
# CHANGELOG_EN.md (2026-05-06) for the full diagnosis.
#
# Saturation eliminated: ``leans_female`` zone (P75 → at_ceiling) now has
# 0.682–0.98 = ~30 % of bar width — wider than zh's 14 % (P75=0.849).
# This is structurally correct: en F P75 = 0.682 sits comfortably below
# the clamp ceiling, so the boundary doesn't need to be pinned to 0.98
# (the way the old empirical 0.987 P75 forced it to be).
_EN_F_P5 = 0.351  # was 0.525 (calibration_v1 v0); shift from 5500 Hz retrain
_EN_F_P25 = 0.458  # was 0.689
_EN_F_P75 = 0.682  # was _AT_CEILING (0.98) — now sub-ceiling, leans_female has real width

_ZONES_EN: tuple[tuple[str, float | None], ...] = (
    ("clearly_below_female", _EN_F_P5),
    ("leans_male", _EN_F_P25),
    ("mid_neutral", _EN_F_P75),
    ("leans_female", _AT_CEILING),
    ("at_ceiling", None),
)


def _zones_for_lang(lang: str) -> tuple[tuple[str, float | None], ...]:
    short = lang.split("-", 1)[0].lower()
    if short == "fr":
        return _ZONES_FR
    if short == "en":
        return _ZONES_EN
    return _ZONES_ZH


def classify_zone(median_resonance: float | None, lang: str) -> str | None:
    """Map a 0-1 ``median_resonance`` value to a zone key.

    Returns ``None`` when the input is None or non-finite, so callers can
    feed the field directly without pre-validation.  Zone keys are stable
    identifiers — i18n lookups happen in advice_v2 / the frontend.
    """
    if median_resonance is None:
        return None
    try:
        v = float(median_resonance)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    zones = _zones_for_lang(lang)
    for key, upper in zones:
        if upper is None or v < upper:
            return key
    # Defensive — the last zone has upper=None so this is unreachable, but
    # belt-and-braces keeps the invariant explicit if someone later adds a
    # bounded top tier.
    return zones[-1][0]


# Public list of zone keys in low → high order.  Useful for tests and for
# i18n key generation in advice_v2 / web/src/modules/i18n.js.
ZONE_KEYS_LOW_TO_HIGH: tuple[str, ...] = tuple(k for k, _ in _ZONES_ZH)
