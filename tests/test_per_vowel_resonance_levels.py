"""Unit tests for advice_v2's per-vowel **resonance score** classifier.

Replaces the F-axis (z_F1/z_F2/z_F3 worst-formant) tests in
test_advice_v2_resonance.py. Locks the good/low/weak thresholds, the
n>=5 token floor, the None-resonance exclusion, and the weakness picker's
top-K behaviour against the panel-level resonance scale.

Run: uv run python tests/test_per_vowel_resonance_levels.py
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voiceya.services.audio_analyser.advice_v2 import (  # noqa: E402
    _VOWEL_RES_GOOD,
    _VOWEL_RES_WEAK,
    _WEAKNESS_MIN_TOKENS,
    _WEAKNESS_TOP_K,
    _build_per_vowel_levels,
    _level_key_by_resonance,
    _pick_weakness_vowels,
)


def _vowel(label: str, *, resonance_med: float | None, n: int = 10) -> dict:
    """Minimal per_vowel entry shaped like engine_c._aggregate_per_vowel output."""
    return {
        "vowel": label,
        "n": n,
        "resonance_med": resonance_med,
        # F-axis fields kept on the source dict (engine_c still emits them)
        # so a stray reader doesn't NPE; the new classifier ignores them.
        "z_F1_med": 0.0,
        "z_F2_med": 0.0,
        "z_F3_med": 0.0,
        "F1_med_hz": 500,
        "F2_med_hz": 1500,
        "F3_med_hz": 2500,
    }


def test_level_key_thresholds() -> None:
    # Boundaries: < 0.40 weak, 0.40–0.65 low, ≥ 0.65 good
    assert _level_key_by_resonance(0.39) == "weak"
    assert _level_key_by_resonance(_VOWEL_RES_WEAK) == "low", "0.40 sits in low"
    assert _level_key_by_resonance(0.50) == "low"
    assert _level_key_by_resonance(0.649) == "low"
    assert _level_key_by_resonance(_VOWEL_RES_GOOD) == "good", "0.65 sits in good"
    assert _level_key_by_resonance(0.95) == "good"
    assert _level_key_by_resonance(None) is None


def test_build_per_vowel_levels_sorts_weak_first() -> None:
    rows = _build_per_vowel_levels(
        [
            _vowel("a", resonance_med=0.85),  # good
            _vowel("e", resonance_med=0.30),  # weak
            _vowel("i", resonance_med=0.55),  # low
            _vowel("o", resonance_med=0.20),  # weak (lower → first)
            _vowel("u", resonance_med=0.70),  # good
        ]
    )
    keys = [(r["vowel"], r["level_key"]) for r in rows]
    # weak rows first (sorted ascending), then low, then good — within each
    # bucket the lower-resonance vowel surfaces first (most actionable).
    assert keys == [
        ("o", "weak"),
        ("e", "weak"),
        ("i", "low"),
        ("u", "good"),
        ("a", "good"),
    ], f"got {keys}"


def test_build_per_vowel_levels_excludes_low_n() -> None:
    rows = _build_per_vowel_levels(
        [
            _vowel("a", resonance_med=0.30, n=_WEAKNESS_MIN_TOKENS - 1),  # too few
            _vowel("e", resonance_med=0.30, n=_WEAKNESS_MIN_TOKENS),  # exactly enough
        ]
    )
    assert [r["vowel"] for r in rows] == ["e"]


def test_build_per_vowel_levels_excludes_none_resonance() -> None:
    rows = _build_per_vowel_levels(
        [
            _vowel("a", resonance_med=None),  # excluded
            _vowel("e", resonance_med=0.30),  # weak
        ]
    )
    assert [r["vowel"] for r in rows] == ["e"]


def test_pick_weakness_top_k_lowest_resonance() -> None:
    cands = _pick_weakness_vowels(
        [
            _vowel("a", resonance_med=0.10),
            _vowel("e", resonance_med=0.20),
            _vowel("i", resonance_med=0.30),
            _vowel("o", resonance_med=0.39),
            _vowel("u", resonance_med=0.50),  # not weak
        ]
    )
    assert len(cands) == _WEAKNESS_TOP_K
    assert [c["vowel"] for c in cands] == ["a", "e", "i"]
    for c in cands:
        assert c["text_key"] == "advice.resonance.weakness.resonance_low"


def test_pick_weakness_skips_at_threshold() -> None:
    # resonance_med == _VOWEL_RES_WEAK is *not* weak (it's low)
    cands = _pick_weakness_vowels(
        [
            _vowel("a", resonance_med=_VOWEL_RES_WEAK),
        ]
    )
    assert cands == []


def test_pick_weakness_excludes_none() -> None:
    cands = _pick_weakness_vowels(
        [
            _vowel("a", resonance_med=None),
            _vowel("e", resonance_med=0.10),
        ]
    )
    assert [c["vowel"] for c in cands] == ["e"]


def _run_all() -> int:
    fns = [
        test_level_key_thresholds,
        test_build_per_vowel_levels_sorts_weak_first,
        test_build_per_vowel_levels_excludes_low_n,
        test_build_per_vowel_levels_excludes_none_resonance,
        test_pick_weakness_top_k_lowest_resonance,
        test_pick_weakness_skips_at_threshold,
        test_pick_weakness_excludes_none,
    ]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
