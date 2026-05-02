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
# within ±0.01 (the audit is deterministic seed=17).
#
#   sex  n   P5     P25    P50    P75    P95    mean
#   F    50  0.490  0.612  0.683  0.842  1.000  0.721
#   M    42  0.234  0.305  0.403  0.518  0.698  0.417
#
# The ``leans_female`` upper bound is set to 0.98 (not F P95 = 1.0) so the
# top tier doesn't require whole-recording score saturation — at the clamp
# ceiling the score has lost discriminative power, so we grade-separate the
# saturated cases as a distinct ``at_ceiling`` tier (UX: a hint that "this
# voice has more headroom than the score can express").
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

# Same boundaries for fr because we don't have a separate fr cis-population
# baseline yet.  Empirically fr post-adaptive-ceiling sits in roughly the
# same dynamic range as zh post-Phase-B (median F ≈ 0.67, gender gap ≈ 0.35
# — Phase A fr vga.json check, 2026-05-01).  Re-anchor when an fr audit
# corpus is available.
_ZONES_FR = _ZONES_ZH

# en: stats.json hasn't been re-trained at 5500 Hz, so the raw score
# distribution still reflects the pre-Phase-B regime (slightly tighter
# bunching at the top).  We classify anyway so the UI gets *some* zone
# label, but the boundaries are imported as-is from zh — accept the
# minor mis-calibration until en gets its own baseline.
_ZONES_EN = _ZONES_ZH


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
