"""Advice v2: measurement + tone tendency (no verdict).

Pure function `compute_advice` produces the `summary.advice` panel described
in docs/plans/v2_redesign_measurement.md §1. Inputs:
  - y, sr               : float32 mono waveform + sample rate (for f0_panel)
  - analyse_results     : Engine A segments with duration + C1 margin
  - duration_sec        : full recording duration

Outputs the advice dict; never raises on missing data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from voiceya.services.audio_analyser.f0_panel import compute_f0_panel

if TYPE_CHECKING:
    from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem


SCHEMA_VERSION = "v2"
TONE_THRESHOLD = 0.78  # see §5; cis_female margin p10 = 0.784 in 95-sample eval

GATING_MINIMAL_MAX_S = 10.0
GATING_STANDARD_MAX_S = 30.0


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
    if weighted_margin < TONE_THRESHOLD or dominant_label not in ("female", "male"):
        return "not_clearly_leaning"
    return "leans_feminine" if dominant_label == "female" else "leans_masculine"


def _weighted_margin(analyse_results: list, dominant_label: str | None) -> float:
    """Duration-weighted C1 margin over segments matching the dominant label.

    Mirrors statics.do_statics so tone_tendency aligns with `overall_confidence`,
    but recomputed locally so advice is a pure function of inputs.
    """
    if dominant_label not in ("female", "male"):
        return 0.0
    total_dur = 0.0
    total_conf_dur = 0.0
    for r in analyse_results:
        if r.label != dominant_label or r.confidence is None:
            continue
        total_dur += r.duration
        total_conf_dur += r.confidence * r.duration
    if total_dur == 0:
        return 0.0
    return total_conf_dur / total_dur


def _summary_text_key(zone_key: str | None, tendency_key: str) -> str | None:
    if zone_key is None:
        return None
    return f"advice.summary.{zone_key}_{tendency_key}"


def compute_advice(
    y: np.ndarray,
    sr: int,
    analyse_results: list[AnalyseResultItem],
    duration_sec: float,
    dominant_label: str | None,
) -> dict:
    """Build the summary.advice panel.

    See docs/plans/v2_redesign_measurement.md §1 for the schema. Output is
    JSON-safe (plain dict / list / float / int / str / None).
    """
    duration_sec = round(float(duration_sec), 2)
    tier = _gating_tier(duration_sec)

    f0_panel = compute_f0_panel(y, sr, duration_sec)
    distribution = _label_distribution(analyse_results, duration_sec)
    weighted_margin = _weighted_margin(analyse_results, dominant_label)
    tendency_key = _tone_tendency(dominant_label, weighted_margin)

    advice: dict = {
        "schema_version": SCHEMA_VERSION,
        "gating_tier": tier,
        "recording_duration_sec": duration_sec,
        "f0_panel": f0_panel,
        "tone_panel": None,
        "summary_panel": None,
        "warnings": [],
    }

    if tier == "minimal":
        advice["warnings"].append({"key": "advice.warning.short_recording_minimal", "params": {}})
        # No tone_panel / summary_panel — gating §3 keeps minimal tier pure.
        return advice

    advice["tone_panel"] = {
        "ina_label_distribution": distribution,
        "tone_tendency_key": tendency_key,
        "caveat_key": "ina.f0_bias_caveat",
    }

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
