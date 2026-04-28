"""Advice v2: file-level F0 measurement (pyin[60-250]).

Used by advice_v2.compute_advice. Separate from acoustic_analyzer._extract_f0
because it intentionally narrows pyin range to avoid octave-doubling on
low-F0 speakers (verified by tests/stress_f0_window.py): pyin[60-1047] gives
~316 Hz on a 176 Hz cis male; pyin[60-250] gives the correct 172 Hz.

Voicing is gated by pyin's own `voiced_flag` (viterbi-smoothed). An earlier
revision layered `voiced_prob > 0.5` on top, but that only retained the
single most-confident harmonic per frame and routinely octave-doubled on
typical cis male voices (e.g. male_2 at 132 Hz reported 206 Hz with 0.7s of
voiced data, vs 132 Hz with 15.3s using voiced_flag alone). voiced_flag
already represents pyin's "this frame is voiced" decision; an extra
threshold on top is double-strict and biases against low-F0 speakers.

Pure: takes (y, sr), returns a panel dict matching docs/plans/v2_redesign_measurement.md §1.
"""

from __future__ import annotations

import logging

import librosa
import numpy as np

logger = logging.getLogger(__name__)

PYIN_FMIN = 60.0
PYIN_FMAX = 250.0
FRAME_LENGTH = 2048
HOP_LENGTH = 512
VOICED_DUR_FLOOR_S = 1.0

# Zone boundaries — see docs/plans/v2_redesign_measurement.md §6.
# Half-open intervals [lo, hi); the last bucket is [240, +inf).
ZONE_LOW_HI = 130.0
ZONE_MID_LOWER_HI = 165.0
ZONE_MID_NEUTRAL_HI = 200.0
ZONE_MID_UPPER_HI = 240.0


def _classify_zone(f0_hz: float) -> str:
    if f0_hz < ZONE_LOW_HI:
        return "low"
    if f0_hz < ZONE_MID_LOWER_HI:
        return "mid_lower"
    if f0_hz < ZONE_MID_NEUTRAL_HI:
        return "mid_neutral"
    if f0_hz < ZONE_MID_UPPER_HI:
        return "mid_upper"
    return "high"


def compute_f0_panel(y: np.ndarray, sr: int, recording_duration_sec: float) -> dict:
    """Compute the f0_panel dict for advice v2.

    Returns the full panel even when F0 is unavailable; downstream gating
    inspects `reliability` rather than panel presence.
    """
    panel: dict = {
        "median_hz": None,
        "p25_hz": None,
        "p75_hz": None,
        "voiced_duration_sec": 0.0,
        "range_zone_key": None,
        "reliability": "insufficient_voiced",
    }

    if y is None or len(y) < FRAME_LENGTH:
        # Audio shorter than one analysis window — gating tier already flags
        # it via recording_duration_sec; no F0 to report.
        if recording_duration_sec < 10.0:
            panel["reliability"] = "short_recording"
        return panel

    try:
        f0, voiced_flag, _voiced_prob = librosa.pyin(
            y,
            fmin=PYIN_FMIN,
            fmax=PYIN_FMAX,
            sr=sr,
            frame_length=FRAME_LENGTH,
            hop_length=HOP_LENGTH,
        )
    except Exception as e:  # pragma: no cover — librosa edge cases (NaN, all-zero)
        logger.warning("pyin[60-250] failed: %s", e)
        if recording_duration_sec < 10.0:
            panel["reliability"] = "short_recording"
        return panel

    voiced_mask = voiced_flag & ~np.isnan(f0)
    voiced_dur = float(voiced_mask.sum() * HOP_LENGTH / sr)
    panel["voiced_duration_sec"] = round(voiced_dur, 2)

    if voiced_dur < VOICED_DUR_FLOOR_S:
        panel["reliability"] = (
            "short_recording" if recording_duration_sec < 10.0 else "insufficient_voiced"
        )
        return panel

    voiced_f0 = f0[voiced_mask]
    median_hz = float(np.median(voiced_f0))
    panel.update(
        median_hz=round(median_hz, 1),
        p25_hz=round(float(np.quantile(voiced_f0, 0.25)), 1),
        p75_hz=round(float(np.quantile(voiced_f0, 0.75)), 1),
        range_zone_key=_classify_zone(median_hz),
        reliability="ok",
    )
    return panel
