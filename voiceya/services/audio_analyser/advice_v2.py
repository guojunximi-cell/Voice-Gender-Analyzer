"""Advice v2: measurement + tone tendency (no verdict).

Pure function `compute_advice` produces the `summary.advice` panel described
in docs/plans/v2_redesign_measurement.md §1. Inputs:
  - y, sr               : float32 mono waveform + sample rate (for f0_panel)
  - analyse_results     : Engine A segments with duration + C1 margin
  - duration_sec        : full recording duration
  - engine_c            : optional summary.engine_c dict (resonance panel)

Outputs the advice dict; never raises on missing data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from voiceya.services.audio_analyser.f0_panel import compute_f0_panel
from voiceya.services.audio_analyser.statics import weighted_confidence

if TYPE_CHECKING:
    from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem


SCHEMA_VERSION = "v2"
TONE_THRESHOLD = 0.78  # see §5; cis_female margin p10 = 0.784 in 95-sample eval
# Below TONE_THRESHOLD but above WEAK_TONE_THRESHOLD: the classifier still leans
# in one direction (margin 0.5 ≈ top class ~75% probability) — surfaced as
# weakly_* so low-confidence directional info isn't lost. Below this, lump as
# not_clearly_leaning.
WEAK_TONE_THRESHOLD = 0.50

GATING_MINIMAL_MAX_S = 10.0
GATING_STANDARD_MAX_S = 30.0

# Resonance weakness picker tuning. n>=5 floor avoids surfacing single-outlier
# vowels in standard tier (where /i/ may appear only 3-4× and one bad
# alignment yanks the median). z<-0.8 cuts noise from vowels essentially at
# the female reference distribution. Top-K=3 caps the card list.
_WEAKNESS_Z_THRESHOLD = -0.8
_WEAKNESS_MIN_TOKENS = 5
_WEAKNESS_TOP_K = 3


def _gating_tier(duration_sec: float) -> str:
    if duration_sec < GATING_MINIMAL_MAX_S:
        return "minimal"
    if duration_sec < GATING_STANDARD_MAX_S:
        return "standard"
    return "full"


def _label_distribution(analyse_results: list, total_duration_sec: float) -> dict:
    """Frame-level label distribution from segment durations.

    `other_frame_ratio` covers everything that is not voiced gendered speech:
    music / noise / silence / unclassified. Always sums to ~1.0 (rounding aside).
    """
    fem = 0.0
    mal = 0.0
    for r in analyse_results:
        if r.label == "female":
            fem += r.duration
        elif r.label == "male":
            mal += r.duration
    fem_ratio = fem / total_duration_sec if total_duration_sec > 0 else 0.0
    mal_ratio = mal / total_duration_sec if total_duration_sec > 0 else 0.0
    other_ratio = max(0.0, 1.0 - fem_ratio - mal_ratio)
    return {
        "female_frame_ratio": round(fem_ratio, 4),
        "male_frame_ratio": round(mal_ratio, 4),
        "other_frame_ratio": round(other_ratio, 4),
    }


def _tone_tendency(dominant_label: str | None, weighted_margin: float) -> str:
    if dominant_label not in ("female", "male"):
        return "not_clearly_leaning"
    if weighted_margin >= TONE_THRESHOLD:
        return "leans_feminine" if dominant_label == "female" else "leans_masculine"
    if weighted_margin >= WEAK_TONE_THRESHOLD:
        return "weakly_feminine" if dominant_label == "female" else "weakly_masculine"
    return "not_clearly_leaning"


def _summary_text_key(zone_key: str | None, tendency_key: str) -> str | None:
    if zone_key is None:
        return None
    return f"advice.summary.{zone_key}_{tendency_key}"


def _pick_weakness_vowels(per_vowel: list[dict]) -> list[dict]:
    """Pick up to top-3 vowels whose worst formant z-score is < -0.8.

    For each vowel we look at the most-negative of (z_F1_med, z_F2_med,
    z_F3_med) — that is, the formant sitting deepest in the male side of
    the female reference distribution. Vowels with n < 5 tokens or whose
    worst formant doesn't cross -0.8 are skipped. Ties broken by smallest z.
    """
    candidates: list[dict] = []
    for v in per_vowel:
        if (v.get("n") or 0) < _WEAKNESS_MIN_TOKENS:
            continue
        formant_z_hz = [
            ("F1", v.get("z_F1_med"), v.get("F1_med_hz")),
            ("F2", v.get("z_F2_med"), v.get("F2_med_hz")),
            ("F3", v.get("z_F3_med"), v.get("F3_med_hz")),
        ]
        valid = [(f, z, hz) for f, z, hz in formant_z_hz if z is not None]
        if not valid:
            continue
        worst_formant, worst_z, worst_hz = min(valid, key=lambda x: x[1])
        if worst_z >= _WEAKNESS_Z_THRESHOLD:
            continue
        candidates.append(
            {
                "vowel": v["vowel"],
                "weakest_formant": worst_formant,
                "z": round(float(worst_z), 2),
                "F_med_hz": worst_hz,
                "n": v["n"],
                "text_key": f"advice.resonance.weakness.{worst_formant}_low",
            }
        )
    candidates.sort(key=lambda c: c["z"])
    return candidates[:_WEAKNESS_TOP_K]


def _resonance_panel(engine_c: dict | None, tier: str) -> dict | None:
    """Build the resonance sub-panel from Engine C output, or None if N/A.

    Skipped entirely on minimal tier (< 10 s recording — per-vowel medians
    are statistically meaningless). Caveat priority: at_ceiling clamp wins
    over alignment quality, since a clamped score actively misleads but
    low alignment just adds noise.
    """
    if not engine_c or tier == "minimal":
        return None
    zone_key = engine_c.get("resonance_zone_key")
    median_resonance = engine_c.get("median_resonance")
    per_vowel = engine_c.get("resonance_per_vowel") or []
    weakness_vowels = _pick_weakness_vowels(per_vowel)

    if zone_key == "at_ceiling":
        caveat_key = "advice.resonance.caveat.score_clamp"
    elif (engine_c.get("alignment_confidence") or {}).get("low_quality"):
        caveat_key = "advice.resonance.caveat.low_alignment"
    else:
        caveat_key = None

    return {
        "zone_key": zone_key,
        "median_resonance": (
            round(float(median_resonance), 3) if median_resonance is not None else None
        ),
        "weakness_vowels": weakness_vowels,
        "summary_text_key": f"advice.resonance.summary.{zone_key}" if zone_key else None,
        "caveat_key": caveat_key,
    }


def compute_advice(
    y: np.ndarray,
    sr: int,
    analyse_results: list[AnalyseResultItem],
    duration_sec: float,
    dominant_label: str | None,
    *,
    weighted_margin: float | None = None,
    f0_panel: dict | None = None,
    engine_c: dict | None = None,
) -> dict:
    """Build the summary.advice panel.

    See docs/plans/v2_redesign_measurement.md §1 for the schema. Output is
    JSON-safe (plain dict / list / float / int / str / None).

    `weighted_margin` is the duration-weighted C1 margin restricted to
    `dominant_label`'s segments. The pipeline (`do_analyse`) passes
    `summary.dominant_confidence` from `statics.do_statics` so a single
    helper (`statics.weighted_confidence`) owns the weighting formula. When
    None (tests / standalone use), it is recomputed via the same helper —
    no parallel implementation here.

    `f0_panel` lets callers pre-compute pyin once and pass it in (the
    pipeline does this so `do_statics.overall_f0_median_hz` and
    `advice.f0_panel.median_hz` come from the same pyin pass). Tests and
    standalone callers can leave it None — we'll compute it ourselves.
    """
    duration_sec = round(float(duration_sec), 2)
    tier = _gating_tier(duration_sec)

    if f0_panel is None:
        f0_panel = compute_f0_panel(y, sr, duration_sec)
    distribution = _label_distribution(analyse_results, duration_sec)
    if weighted_margin is None:
        weighted_margin = weighted_confidence(analyse_results, label_filter=dominant_label)
    tendency_key = _tone_tendency(dominant_label, weighted_margin)

    advice: dict = {
        "schema_version": SCHEMA_VERSION,
        "gating_tier": tier,
        "recording_duration_sec": duration_sec,
        "f0_panel": f0_panel,
        "tone_panel": None,
        "summary_panel": None,
        "resonance_panel": None,
        "warnings": [],
    }

    if tier == "minimal":
        advice["warnings"].append({"key": "advice.warning.short_recording_minimal", "params": {}})
        # No tone_panel / summary_panel / resonance_panel — gating §3 keeps minimal tier pure.
        return advice

    advice["tone_panel"] = {
        "ina_label_distribution": distribution,
        "tone_tendency_key": tendency_key,
        "caveat_key": "ina.f0_bias_caveat",
    }

    advice["resonance_panel"] = _resonance_panel(engine_c, tier)

    text_key = _summary_text_key(f0_panel.get("range_zone_key"), tendency_key)
    if text_key is not None:
        advice["summary_panel"] = {
            "text_key": text_key,
            "text_params": {"f0": int(round(f0_panel["median_hz"]))},
        }
    # else: F0 unreliable → no summary template fits; UI shows f0_panel reliability.

    if tier == "standard":
        advice["warnings"].append(
            {
                "key": "advice.warning.short_recording_standard",
                "params": {"duration": int(round(duration_sec))},
            }
        )

    return advice
