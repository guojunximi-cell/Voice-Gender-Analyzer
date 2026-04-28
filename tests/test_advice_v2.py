"""Unit tests for advice_v2.compute_advice.

Pure-logic tests (no audio file IO, no Engine A) that lock the gating tier,
zone classification, and tone tendency contracts described in
docs/plans/v2_redesign_measurement.md §1, §3, §5.

Run: .venv/bin/python tests/test_advice_v2.py
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np  # noqa: E402

from voiceya.services.audio_analyser.advice_v2 import compute_advice  # noqa: E402
from voiceya.services.audio_analyser.f0_panel import _classify_zone  # noqa: E402
from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem  # noqa: E402


def _seg(label: str, dur: float, conf: float | None) -> AnalyseResultItem:
    return AnalyseResultItem(
        label=label,
        start_time=0.0,
        end_time=dur,
        duration=dur,
        confidence=conf,
        confidence_frames=None,
        acoustics=None,
    )


# ─── zone classification ────────────────────────────────────────────


def test_zone_low():
    assert _classify_zone(100.0) == "low"
    assert _classify_zone(129.9) == "low"


def test_zone_mid_lower():
    assert _classify_zone(130.0) == "mid_lower"
    assert _classify_zone(150.0) == "mid_lower"
    assert _classify_zone(164.9) == "mid_lower"


def test_zone_mid_neutral_anchored_to_caveat():
    """Caveat text says 165-200 Hz unreliable; mid_neutral must match."""
    assert _classify_zone(165.0) == "mid_neutral"
    assert _classify_zone(180.0) == "mid_neutral"
    assert _classify_zone(199.9) == "mid_neutral"


def test_zone_mid_upper():
    assert _classify_zone(200.0) == "mid_upper"
    assert _classify_zone(239.9) == "mid_upper"


def test_zone_high():
    assert _classify_zone(240.0) == "high"
    assert _classify_zone(300.0) == "high"


# ─── gating tier ────────────────────────────────────────────────────


def _empty_y():
    return np.zeros(0, dtype=np.float32), 16_000


def test_gating_minimal_under_10s():
    y, sr = _empty_y()
    out = compute_advice(y, sr, [], duration_sec=8.0, dominant_label=None)
    assert out["gating_tier"] == "minimal"
    assert out["tone_panel"] is None
    assert out["summary_panel"] is None
    assert out["warnings"][0]["key"] == "advice.warning.short_recording_minimal"


def test_gating_standard_10_to_30():
    y, sr = _empty_y()
    out = compute_advice(y, sr, [], duration_sec=20.0, dominant_label=None)
    assert out["gating_tier"] == "standard"
    assert out["warnings"][0]["key"] == "advice.warning.short_recording_standard"
    assert out["warnings"][0]["params"]["duration"] == 20


def test_gating_full_30s_no_warning():
    y, sr = _empty_y()
    out = compute_advice(y, sr, [], duration_sec=30.0, dominant_label=None)
    assert out["gating_tier"] == "full"
    assert out["warnings"] == []


# ─── tone tendency ──────────────────────────────────────────────────


def test_tendency_leans_feminine_at_threshold():
    """0.78 is the leans/not-clearly boundary — exactly 0.78 leans."""
    y, sr = _empty_y()
    items = [_seg("female", 30.0, 0.78)]
    out = compute_advice(y, sr, items, 30.0, "female")
    assert out["tone_panel"]["tone_tendency_key"] == "leans_feminine"


def test_tendency_below_threshold_unclear():
    y, sr = _empty_y()
    items = [_seg("female", 30.0, 0.50)]
    out = compute_advice(y, sr, items, 30.0, "female")
    assert out["tone_panel"]["tone_tendency_key"] == "not_clearly_leaning"


def test_tendency_leans_masculine():
    y, sr = _empty_y()
    items = [_seg("male", 30.0, 0.90)]
    out = compute_advice(y, sr, items, 30.0, "male")
    assert out["tone_panel"]["tone_tendency_key"] == "leans_masculine"


def test_tendency_no_dominant_label():
    """No voiced gendered segments → not_clearly_leaning regardless of margin."""
    y, sr = _empty_y()
    out = compute_advice(y, sr, [], 30.0, None)
    assert out["tone_panel"]["tone_tendency_key"] == "not_clearly_leaning"


# ─── distribution ───────────────────────────────────────────────────


def test_distribution_sums_to_one():
    y, sr = _empty_y()
    items = [_seg("female", 8.0, 0.9), _seg("male", 2.0, 0.6), _seg("noise", 5.0, None)]
    out = compute_advice(y, sr, items, 15.0, "female")
    dist = out["tone_panel"]["ina_label_distribution"]
    total = dist["female_frame_ratio"] + dist["male_frame_ratio"] + dist["other_frame_ratio"]
    assert abs(total - 1.0) < 1e-3, total
    assert abs(dist["female_frame_ratio"] - 8.0 / 15.0) < 1e-3
    assert abs(dist["male_frame_ratio"] - 2.0 / 15.0) < 1e-3


# ─── caveat key always present in tone_panel ───────────────────────


def test_caveat_key_present():
    """Caveat is permanent (§2) — every tone_panel must carry the key."""
    y, sr = _empty_y()
    out = compute_advice(y, sr, [_seg("female", 30.0, 0.9)], 30.0, "female")
    assert out["tone_panel"]["caveat_key"] == "ina.f0_bias_caveat"


# ─── schema integrity ──────────────────────────────────────────────


def test_schema_version_v2():
    y, sr = _empty_y()
    out = compute_advice(y, sr, [], 30.0, None)
    assert out["schema_version"] == "v2"


def test_summary_panel_only_with_valid_zone():
    """No F0 → no summary template fits → summary_panel is None."""
    y, sr = _empty_y()
    out = compute_advice(y, sr, [_seg("female", 30.0, 0.9)], 30.0, "female")
    # f0_panel.range_zone_key is None for empty audio → summary_panel None
    assert out["f0_panel"]["range_zone_key"] is None
    assert out["summary_panel"] is None


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
