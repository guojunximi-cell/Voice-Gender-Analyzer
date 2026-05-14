"""Standalone tests for per-phone resonance aggregation + advice gating.

Covers the 2026-05-08 widening:
  - engine_c._aggregate_per_vowel now buckets *all* phones with a
    non-null ``resonance``, tagging each with ``is_vowel``; min token
    count dropped 3 → 2.
  - advice_v2._WEAKNESS_MIN_TOKENS dropped 5 → 2 in lockstep.
  - advice_v2._pick_weakness_vowels filters on ``is_vowel`` so weakness
    coaching stays vowel-only even though display includes consonants.

Run: ``python tests/test_per_vowel_min_tokens.py`` from repo root.
"""

from __future__ import annotations

import os
import sys
import traceback

# Repo root on path so `import voiceya.…` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voiceya.services.audio_analyser.advice_v2 import (  # noqa: E402
    _build_per_vowel_levels,
    _pick_weakness_vowels,
)
from voiceya.services.audio_analyser.engine_c import (  # noqa: E402
    _aggregate_per_vowel,
    _build_phone_array,
    _phone_is_vowel,
)


def _phone(
    label: str, resonance: float, *, F1: float = 600, F2: float = 1500, F3: float = 2500
) -> dict:
    """Build a phone dict shaped like _build_phone_array's output."""
    return {
        "phone": label,
        "start": 0.0,
        "end": 0.1,
        "resonance": resonance,
        "F1": F1,
        "F2": F2,
        "F3": F3,
        "z_F1": -0.1,
        "z_F2": 0.1,
        "z_F3": -0.2,
    }


# ── _aggregate_per_vowel ─────────────────────────────────────────────


def test_aggregate_includes_consonants_with_is_vowel_flag():
    """3× /o/ + 2× /m/ → both bucketed; is_vowel marks origin."""
    phones = [
        _phone("o", 0.10),
        _phone("o", 0.05),
        _phone("o", 0.08),
        _phone("m", 0.55),
        _phone("m", 0.62),
    ]
    out = _aggregate_per_vowel(phones, "zh")
    assert len(out) == 2, f"expected 2 buckets, got {len(out)}: {out}"
    by_label = {row["vowel"]: row for row in out}
    assert "o" in by_label and "m" in by_label
    assert by_label["o"]["is_vowel"] is True, "/o/ should be flagged is_vowel"
    assert by_label["m"]["is_vowel"] is False, "/m/ is sonorant, not vowel"
    assert by_label["o"]["n"] == 3
    assert by_label["m"]["n"] == 2


def test_aggregate_drops_below_min_tokens():
    """n=1 phone is dropped; n=2 survives (threshold lowered 3→2)."""
    phones = [
        _phone("o", 0.10),
        _phone("o", 0.05),  # n=2 — keeps
        _phone("a", 0.30),  # n=1 — drops
    ]
    out = _aggregate_per_vowel(phones, "zh")
    labels = {row["vowel"] for row in out}
    assert labels == {"o"}, f"expected only /o/, got {labels}"


def test_aggregate_skips_phones_without_resonance():
    """Phones the sidecar couldn't score (resonance=None) are excluded."""
    phones = [
        _phone("o", 0.10),
        _phone("o", 0.05),
        _phone(
            "p", None
        ),  # voiceless plosive: no F-stdevs → no resonance  # type: ignore[arg-type]
        _phone("p", None),  # type: ignore[arg-type]
    ]
    out = _aggregate_per_vowel(phones, "zh")
    labels = {row["vowel"] for row in out}
    assert labels == {"o"}, f"resonance=None must be skipped, got {labels}"


def test_aggregate_zh_strips_tone_diacritics():
    """zh: /a˥˥/ + /a˧˩˧/ collapse into one /a/ bucket."""
    phones = [
        _phone("a˥˥", 0.40),  # tone 1
        _phone("a˧˩˧", 0.45),  # tone 3
    ]
    out = _aggregate_per_vowel(phones, "zh")
    assert len(out) == 1
    assert out[0]["vowel"] == "a"
    assert out[0]["n"] == 2


def test_aggregate_en_strips_arpabet_stress_digit():
    """en: IY1 + IY0 collapse into IY bucket; consonants pass through."""
    phones = [
        {
            "phone": "IY1",
            "start": 0.0,
            "end": 0.1,
            "resonance": 0.4,
            "F1": 380,
            "F2": 2400,
            "F3": 3100,
            "z_F1": 0.0,
            "z_F2": 0.0,
            "z_F3": 0.0,
        },
        {
            "phone": "IY0",
            "start": 0.1,
            "end": 0.2,
            "resonance": 0.45,
            "F1": 380,
            "F2": 2400,
            "F3": 3100,
            "z_F1": 0.0,
            "z_F2": 0.0,
            "z_F3": 0.0,
        },
        {
            "phone": "M",
            "start": 0.2,
            "end": 0.3,
            "resonance": 0.6,
            "F1": 300,
            "F2": 1200,
            "F3": 2400,
            "z_F1": 0.0,
            "z_F2": 0.0,
            "z_F3": 0.0,
        },
        {
            "phone": "M",
            "start": 0.3,
            "end": 0.4,
            "resonance": 0.65,
            "F1": 310,
            "F2": 1210,
            "F3": 2400,
            "z_F1": 0.0,
            "z_F2": 0.0,
            "z_F3": 0.0,
        },
    ]
    out = _aggregate_per_vowel(phones, "en")
    by_label = {row["vowel"]: row for row in out}
    assert "IY" in by_label and "M" in by_label
    assert by_label["IY"]["is_vowel"] is True
    assert by_label["M"]["is_vowel"] is False


# ── advice_v2._pick_weakness_vowels ──────────────────────────────────


def test_weakness_picks_only_vowels():
    """Sonorants in per_vowel never appear in weakness coaching, even when
    their resonance is below the weak threshold."""
    per_vowel = [
        {"vowel": "o", "n": 5, "resonance_med": 0.10, "is_vowel": True},
        {"vowel": "i", "n": 4, "resonance_med": 0.20, "is_vowel": True},
        {"vowel": "m", "n": 5, "resonance_med": 0.15, "is_vowel": False},
        {"vowel": "n", "n": 3, "resonance_med": 0.05, "is_vowel": False},
    ]
    picks = _pick_weakness_vowels(per_vowel)
    labels = [p["vowel"] for p in picks]
    assert labels == ["o", "i"], f"expected vowels only, got {labels}"


def test_weakness_picks_respect_n_floor():
    """n < _WEAKNESS_MIN_TOKENS (=2) is dropped from weakness coaching."""
    per_vowel = [
        {"vowel": "o", "n": 1, "resonance_med": 0.10, "is_vowel": True},  # drops
        {"vowel": "i", "n": 2, "resonance_med": 0.20, "is_vowel": True},  # keeps
    ]
    picks = _pick_weakness_vowels(per_vowel)
    assert [p["vowel"] for p in picks] == ["i"]


def test_weakness_picks_back_compat_no_is_vowel_field():
    """Older cached entries without is_vowel default to True (vowel)."""
    per_vowel = [
        {"vowel": "o", "n": 5, "resonance_med": 0.10},  # no is_vowel key
    ]
    picks = _pick_weakness_vowels(per_vowel)
    assert [p["vowel"] for p in picks] == ["o"]


# ── advice_v2._build_per_vowel_levels ────────────────────────────────


def test_per_vowel_levels_includes_consonants():
    """Display list includes is_vowel=False rows so the UI can render them
    with distinct styling under the toggle."""
    per_vowel = [
        {"vowel": "o", "n": 3, "resonance_med": 0.10, "is_vowel": True},
        {"vowel": "m", "n": 2, "resonance_med": 0.55, "is_vowel": False},
    ]
    levels = _build_per_vowel_levels(per_vowel)
    by_label = {r["vowel"]: r for r in levels}
    assert set(by_label) == {"o", "m"}
    assert by_label["o"]["is_vowel"] is True
    assert by_label["m"]["is_vowel"] is False
    # level_key sourced from _level_key_by_resonance: <0.40 weak, [0.40,0.65) low, >=0.65 good
    assert by_label["o"]["level_key"] == "weak"
    assert by_label["m"]["level_key"] == "low"


# ── _phone_is_vowel + _build_phone_array (per-phone is_vowel field) ──


def test_phone_is_vowel_zh_strips_tones():
    """zh: tone diacritics don't break vowel detection."""
    assert _phone_is_vowel("a", "zh") is True
    assert _phone_is_vowel("a˥˥", "zh") is True  # tone 1
    assert _phone_is_vowel("o˧˩˧", "zh") is True  # tone 3
    assert _phone_is_vowel("m", "zh") is False  # nasal sonorant
    assert _phone_is_vowel("ʈʂ", "zh") is False  # affricate


def test_phone_is_vowel_en_strips_stress():
    """en: ARPABET stress digits don't break vowel detection."""
    assert _phone_is_vowel("IY", "en") is True
    assert _phone_is_vowel("IY1", "en") is True
    assert _phone_is_vowel("AH0", "en") is True
    assert _phone_is_vowel("M", "en") is False
    assert _phone_is_vowel("S", "en") is False


def test_phone_is_vowel_unknown_lang_returns_false():
    """Defensive: an unknown lang_short shouldn't crash, just say not-vowel."""
    assert _phone_is_vowel("a", "xx") is False
    assert _phone_is_vowel("", "zh") is False


def test_build_phone_array_tags_is_vowel_per_phone():
    """_build_phone_array surfaces is_vowel so the frontend can filter."""
    raw = [
        {
            "time": 0.0,
            "phoneme": "a˥˥",
            "F": [120, 700, 1500, 2800],
            "F_stdevs": [0, 0.1, 0.2, 0.0],
            "resonance": 0.5,
        },
        {
            "time": 0.1,
            "phoneme": "m",
            "F": [110, 300, 1200, 2400],
            "F_stdevs": [0, -0.5, -0.8, 0.0],
            "resonance": 0.4,
        },
        {
            "time": 0.2,
            "phoneme": "i",
            "F": [130, 380, 2400, 3100],
            "F_stdevs": [0, 0.3, 0.1, -0.1],
            "resonance": 0.6,
        },
    ]
    phones = _build_phone_array(raw, [], "zh")
    assert len(phones) == 3
    by_phone = {p["phone"]: p for p in phones}
    assert by_phone["a˥˥"]["is_vowel"] is True
    assert by_phone["m"]["is_vowel"] is False
    assert by_phone["i"]["is_vowel"] is True


def test_per_vowel_levels_skip_below_n_floor():
    """n < 2 is dropped from display list."""
    per_vowel = [
        {"vowel": "o", "n": 1, "resonance_med": 0.50, "is_vowel": True},
    ]
    assert _build_per_vowel_levels(per_vowel) == []


# ── Runner ───────────────────────────────────────────────────────────


def _run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
