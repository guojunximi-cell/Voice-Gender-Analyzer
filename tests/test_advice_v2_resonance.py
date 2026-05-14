"""Unit tests for advice_v2._resonance_panel + _pick_weakness_vowels.

DISABLED 2026-05-04: per-vowel level classification migrated from worst-formant
z-score to per-vowel resonance score. New tests live in
tests/test_per_vowel_resonance_levels.py. The body below is preserved so a
future revert can restore the F-axis logic without rewriting test fixtures.

Run: uv run python tests/test_advice_v2_resonance.py
"""

from __future__ import annotations

import sys

print(
    "[skip] test_advice_v2_resonance.py — F-axis tests retired; see tests/test_per_vowel_resonance_levels.py"
)
sys.exit(0)

# ─── ORIGINAL TESTS BELOW (kept for revival) ─────────────────────────────────
import os  # noqa: E402, F401
import traceback  # noqa: E402, F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np  # noqa: E402, F401

from voiceya.services.audio_analyser.advice_v2 import (  # noqa: E402, F401
    _WEAKNESS_MIN_TOKENS,
    _WEAKNESS_TOP_K,
    _WEAKNESS_Z_THRESHOLD,
    _build_per_vowel_levels,
    _level_key,
    _pick_weakness_vowels,
    _resonance_panel,
    compute_advice,
)
from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem  # noqa: E402, F401


def _vowel(
    label: str,
    n: int = 10,
    *,
    z_F1: float | None = 0.0,
    z_F2: float | None = 0.0,
    z_F3: float | None = 0.0,
    F1: int | None = 500,
    F2: int | None = 1500,
    F3: int | None = 2500,
) -> dict:
    return {
        "vowel": label,
        "n": n,
        "z_F1_med": z_F1,
        "z_F2_med": z_F2,
        "z_F3_med": z_F3,
        "F1_med_hz": F1,
        "F2_med_hz": F2,
        "F3_med_hz": F3,
    }


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


# ─── _pick_weakness_vowels ─────────────────────────────────────────


def test_picker_empty_input():
    assert _pick_weakness_vowels([]) == []


def test_picker_threshold_inclusive_boundary_excludes_minus_zero_eight():
    """z exactly at -0.8 is NOT a weakness — strict < threshold."""
    assert _WEAKNESS_Z_THRESHOLD == -0.8
    assert _pick_weakness_vowels([_vowel("a", n=10, z_F2=-0.80)]) == []


def test_picker_just_below_threshold_included():
    out = _pick_weakness_vowels([_vowel("a", n=10, z_F2=-0.81)])
    assert len(out) == 1
    assert out[0]["weakest_formant"] == "F2"
    assert out[0]["text_key"] == "advice.resonance.weakness.F2_low"


def test_picker_n_below_five_dropped():
    """Soft floor n>=5 protects against single-outlier medians in standard tier."""
    assert _WEAKNESS_MIN_TOKENS == 5
    assert _pick_weakness_vowels([_vowel("a", n=4, z_F2=-2.0)]) == []
    assert len(_pick_weakness_vowels([_vowel("a", n=5, z_F2=-2.0)])) == 1


def test_picker_top_k_cap_at_three():
    """Many candidates → only top 3 by smallest z survive."""
    assert _WEAKNESS_TOP_K == 3
    candidates = [
        _vowel("a", n=10, z_F2=-0.85),
        _vowel("e", n=10, z_F2=-1.20),
        _vowel("i", n=10, z_F2=-1.50),
        _vowel("o", n=10, z_F2=-2.00),
        _vowel("u", n=10, z_F2=-0.90),
    ]
    out = _pick_weakness_vowels(candidates)
    assert len(out) == 3
    # Sorted most negative first, so /o/, /i/, /e/ — /a/ and /u/ dropped.
    assert [v["vowel"] for v in out] == ["o", "i", "e"]


def test_picker_picks_most_negative_formant_per_vowel():
    """For a vowel with multiple negative formants, weakest_formant is the smallest z."""
    out = _pick_weakness_vowels(
        [_vowel("i", n=10, z_F1=-0.85, z_F2=-1.50, z_F3=-1.10, F1=380, F2=1900, F3=2700)]
    )
    assert len(out) == 1
    assert out[0]["weakest_formant"] == "F2"
    assert out[0]["z"] == -1.5
    assert out[0]["F_med_hz"] == 1900


def test_picker_skips_vowel_with_all_none_z():
    out = _pick_weakness_vowels([_vowel("a", n=10, z_F1=None, z_F2=None, z_F3=None)])
    assert out == []


def test_picker_handles_partial_none_z():
    """If only z_F2 present and < threshold, it wins even if F1/F3 are None."""
    out = _pick_weakness_vowels(
        [_vowel("a", n=10, z_F1=None, z_F2=-1.0, z_F3=None, F1=None, F2=1300, F3=None)]
    )
    assert len(out) == 1
    assert out[0]["weakest_formant"] == "F2"
    assert out[0]["F_med_hz"] == 1300


def test_picker_text_key_per_formant():
    out_f1 = _pick_weakness_vowels([_vowel("a", n=10, z_F1=-1.5)])
    assert out_f1[0]["text_key"] == "advice.resonance.weakness.F1_low"
    out_f3 = _pick_weakness_vowels([_vowel("a", n=10, z_F3=-1.5)])
    assert out_f3[0]["text_key"] == "advice.resonance.weakness.F3_low"


# ─── _resonance_panel — minimal tier guard + None inputs ───────────


def test_panel_none_engine_c_returns_none():
    assert _resonance_panel(None, "full") is None
    assert _resonance_panel(None, "standard") is None


def test_panel_minimal_tier_returns_none_even_with_data():
    """Per-vowel medians are statistically meaningless < 10s — always None."""
    ec = {"resonance_zone_key": "leans_female", "median_resonance": 0.7}
    assert _resonance_panel(ec, "minimal") is None


def test_panel_standard_tier_emits():
    ec = {"resonance_zone_key": "mid_neutral", "median_resonance": 0.5}
    out = _resonance_panel(ec, "standard")
    assert out is not None
    assert out["zone_key"] == "mid_neutral"
    assert out["summary_text_key"] == "advice.resonance.summary.mid_neutral"


# ─── _resonance_panel — caveat priority ────────────────────────────


def test_panel_caveat_at_ceiling_wins_over_low_alignment():
    """Clamped score actively misleads, so it wins even if alignment is also bad."""
    ec = {
        "resonance_zone_key": "at_ceiling",
        "median_resonance": 1.0,
        "alignment_confidence": {"low_quality": True},
    }
    out = _resonance_panel(ec, "full")
    assert out["caveat_key"] == "advice.resonance.caveat.score_clamp"


def test_panel_caveat_low_alignment_when_zone_ok():
    ec = {
        "resonance_zone_key": "leans_female",
        "median_resonance": 0.65,
        "alignment_confidence": {"low_quality": True},
    }
    out = _resonance_panel(ec, "full")
    assert out["caveat_key"] == "advice.resonance.caveat.low_alignment"


def test_panel_no_caveat_when_clean():
    ec = {
        "resonance_zone_key": "mid_neutral",
        "median_resonance": 0.5,
        "alignment_confidence": {"low_quality": False},
    }
    out = _resonance_panel(ec, "full")
    assert out["caveat_key"] is None


# ─── _resonance_panel — 5 zone × weakness scenarios ────────────────


def _ec_with_per_vowel(zone: str, per_vowel: list[dict]) -> dict:
    return {
        "resonance_zone_key": zone,
        "median_resonance": 0.5,
        "resonance_per_vowel": per_vowel,
        "alignment_confidence": {"low_quality": False},
    }


def test_panel_zone_clearly_below_female_with_weakness():
    ec = _ec_with_per_vowel(
        "clearly_below_female",
        [_vowel("a", n=10, z_F2=-1.5), _vowel("i", n=10, z_F2=-1.2)],
    )
    out = _resonance_panel(ec, "full")
    assert out["zone_key"] == "clearly_below_female"
    assert len(out["weakness_vowels"]) == 2


def test_panel_zone_leans_male_no_weakness():
    """Even when zone is sub-optimal, all per-vowel z above threshold → empty list."""
    ec = _ec_with_per_vowel("leans_male", [_vowel("a", n=10, z_F2=-0.4)])
    out = _resonance_panel(ec, "full")
    assert out["weakness_vowels"] == []


def test_panel_zone_mid_neutral_single_weakness():
    ec = _ec_with_per_vowel("mid_neutral", [_vowel("i", n=10, z_F2=-1.0)])
    out = _resonance_panel(ec, "full")
    assert len(out["weakness_vowels"]) == 1
    assert out["weakness_vowels"][0]["vowel"] == "i"


def test_panel_zone_leans_female_top_three_only():
    ec = _ec_with_per_vowel(
        "leans_female",
        [
            _vowel("a", n=10, z_F2=-1.0),
            _vowel("e", n=10, z_F2=-1.5),
            _vowel("i", n=10, z_F2=-2.0),
            _vowel("o", n=10, z_F2=-0.85),
        ],
    )
    out = _resonance_panel(ec, "full")
    assert len(out["weakness_vowels"]) == 3
    assert [v["vowel"] for v in out["weakness_vowels"]] == ["i", "e", "a"]


def test_panel_zone_at_ceiling_caveat_only():
    ec = _ec_with_per_vowel("at_ceiling", [])
    out = _resonance_panel(ec, "full")
    assert out["zone_key"] == "at_ceiling"
    assert out["caveat_key"] == "advice.resonance.caveat.score_clamp"
    assert out["weakness_vowels"] == []


# ─── _level_key + _build_per_vowel_levels ─────────────────────────


def test_level_key_boundaries():
    """good ≥ 0.0; low ∈ [-0.8, 0.0); weak < -0.8. Both edges check inclusivity."""
    assert _level_key(0.5) == "good"
    assert _level_key(0.0) == "good"  # exactly 0 is good (at reference)
    assert _level_key(-0.01) == "low"
    assert _level_key(-0.5) == "low"
    assert _level_key(-0.8) == "low"  # exactly -0.8 is low (matches strict weakness threshold)
    assert _level_key(-0.81) == "weak"
    assert _level_key(-2.0) == "weak"


def test_per_vowel_levels_drops_n_below_five():
    """Same n>=5 floor as the weakness picker — single-outlier vowels stay out."""
    out = _build_per_vowel_levels([_vowel("a", n=4, z_F2=-1.5)])
    assert out == []
    assert len(_build_per_vowel_levels([_vowel("a", n=5, z_F2=-1.5)])) == 1


def test_per_vowel_levels_drops_all_none_z():
    out = _build_per_vowel_levels([_vowel("a", n=10, z_F1=None, z_F2=None, z_F3=None)])
    assert out == []


def test_per_vowel_levels_assigns_correct_buckets():
    """One vowel per bucket: pick by worst formant."""
    out = _build_per_vowel_levels(
        [
            _vowel("a", n=10, z_F1=0.3, z_F2=0.5, z_F3=0.4),  # good
            _vowel("e", n=10, z_F1=-0.2, z_F2=0.5, z_F3=0.4),  # low (worst is F1=-0.2)
            _vowel("i", n=10, z_F1=0.5, z_F2=-1.5, z_F3=0.0),  # weak (worst is F2=-1.5)
        ]
    )
    by_vowel = {r["vowel"]: r for r in out}
    assert by_vowel["a"]["level_key"] == "good"
    assert by_vowel["e"]["level_key"] == "low"
    assert by_vowel["e"]["weakest_formant"] == "F1"
    assert by_vowel["i"]["level_key"] == "weak"
    assert by_vowel["i"]["weakest_formant"] == "F2"


def test_per_vowel_levels_sort_order():
    """weak → low → good, then by z ascending within each bucket.

    z_F1 / z_F3 pinned to +1.0 so F2 is unambiguously the worst formant for
    every vowel — otherwise the default z=0 on F1/F3 would tie for "good".
    """
    out = _build_per_vowel_levels(
        [
            _vowel("a", n=10, z_F1=1.0, z_F2=0.4, z_F3=1.0),  # good (z=0.4)
            _vowel("e", n=10, z_F1=1.0, z_F2=-0.3, z_F3=1.0),  # low
            _vowel("i", n=10, z_F1=1.0, z_F2=-1.2, z_F3=1.0),  # weak
            _vowel("o", n=10, z_F1=1.0, z_F2=0.1, z_F3=1.0),  # good (less good than /a/)
            _vowel("u", n=10, z_F1=1.0, z_F2=-2.0, z_F3=1.0),  # weak (most negative)
            _vowel("y", n=10, z_F1=1.0, z_F2=-0.6, z_F3=1.0),  # low (more neg than /e/)
        ]
    )
    # weak (u, i) → low (y, e) → good (o, a). Within each bucket: z ascending.
    assert [r["vowel"] for r in out] == ["u", "i", "y", "e", "o", "a"]


def test_per_vowel_levels_superset_of_weakness():
    """Every weakness vowel must appear in per_vowel with level_key == 'weak'."""
    per_vowel_input = [
        _vowel("a", n=10, z_F2=-0.3),  # low
        _vowel("e", n=10, z_F2=-1.5),  # weak
        _vowel("i", n=10, z_F2=-1.0),  # weak
    ]
    weakness = _pick_weakness_vowels(per_vowel_input)
    levels = _build_per_vowel_levels(per_vowel_input)
    weak_in_levels = {r["vowel"] for r in levels if r["level_key"] == "weak"}
    assert {w["vowel"] for w in weakness} <= weak_in_levels


def test_panel_emits_per_vowel_field():
    """_resonance_panel returns a per_vowel list alongside weakness_vowels."""
    ec = _ec_with_per_vowel(
        "mid_neutral",
        [
            _vowel("a", n=10, z_F2=0.4),  # good
            _vowel("e", n=10, z_F2=-1.2),  # weak
            _vowel("i", n=10, z_F2=-0.5),  # low
            _vowel("o", n=4, z_F2=-2.0),  # filtered (n<5)
        ],
    )
    out = _resonance_panel(ec, "full")
    assert "per_vowel" in out
    assert len(out["per_vowel"]) == 3  # /o/ filtered
    assert {r["vowel"] for r in out["per_vowel"]} == {"a", "e", "i"}


# ─── median_resonance rounding ─────────────────────────────────────


def test_panel_median_rounded_to_three_dp():
    ec = {"resonance_zone_key": "mid_neutral", "median_resonance": 0.6789}
    out = _resonance_panel(ec, "full")
    assert out["median_resonance"] == 0.679


def test_panel_median_none_passthrough():
    ec = {"resonance_zone_key": "mid_neutral", "median_resonance": None}
    out = _resonance_panel(ec, "full")
    assert out["median_resonance"] is None


# ─── compute_advice end-to-end wiring ──────────────────────────────


def _empty_y():
    return np.zeros(0, dtype=np.float32), 16_000


def test_compute_advice_no_engine_c_no_resonance_panel():
    y, sr = _empty_y()
    out = compute_advice(y, sr, [_seg("female", 30.0, 0.9)], 30.0, "female")
    assert "resonance_panel" in out
    assert out["resonance_panel"] is None


def test_compute_advice_minimal_tier_no_resonance_panel():
    """Even with engine_c data, minimal tier suppresses the panel."""
    y, sr = _empty_y()
    ec = _ec_with_per_vowel("leans_female", [_vowel("a", n=10, z_F2=-1.5)])
    out = compute_advice(y, sr, [], 5.0, None, engine_c=ec)
    assert out["gating_tier"] == "minimal"
    assert out["resonance_panel"] is None


def test_compute_advice_full_tier_with_engine_c_emits_panel():
    y, sr = _empty_y()
    ec = _ec_with_per_vowel(
        "leans_female",
        [_vowel("i", n=10, z_F2=-1.2, F2=1900)],
    )
    out = compute_advice(y, sr, [_seg("female", 30.0, 0.9)], 30.0, "female", engine_c=ec)
    panel = out["resonance_panel"]
    assert panel is not None
    assert panel["zone_key"] == "leans_female"
    assert len(panel["weakness_vowels"]) == 1
    assert panel["weakness_vowels"][0]["vowel"] == "i"
    assert panel["weakness_vowels"][0]["F_med_hz"] == 1900


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
