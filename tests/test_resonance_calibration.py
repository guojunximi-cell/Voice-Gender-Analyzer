"""Tests for resonance_calibration.classify_zone + engine_c per-vowel
aggregation surface (Phase C of the resonance score interpretation work
— see docs/plans/v2_redesign_measurement.md and tests/reports/
zh_resonance_baseline_2026-05-01.md).

Run directly (no pytest) per the project convention:

    uv run python tests/test_resonance_calibration.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voiceya.services.audio_analyser import engine_c, resonance_calibration  # noqa: E402

# ── classify_zone — boundary + lang variants ────────────────────────


def test_classify_zone_boundary_zh():
    # Boundaries copy the constants from resonance_calibration so a
    # threshold change in the module surfaces as a visible test diff.
    assert resonance_calibration.classify_zone(0.0, "zh-CN") == "clearly_below_female"
    assert resonance_calibration.classify_zone(0.489, "zh-CN") == "clearly_below_female"
    # Half-open intervals: equal-to-lower-bound lands in the higher tier.
    assert resonance_calibration.classify_zone(0.490, "zh-CN") == "leans_male"
    assert resonance_calibration.classify_zone(0.611, "zh-CN") == "leans_male"
    assert resonance_calibration.classify_zone(0.612, "zh-CN") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.841, "zh-CN") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.842, "zh-CN") == "leans_female"
    assert resonance_calibration.classify_zone(0.979, "zh-CN") == "leans_female"
    assert resonance_calibration.classify_zone(0.98, "zh-CN") == "at_ceiling"
    assert resonance_calibration.classify_zone(1.0, "zh-CN") == "at_ceiling"


def test_classify_zone_lang_aliases():
    # BCP-47 ↔ short codes both routed.  zh has its own anchored table
    # (Phase B / 2026-05-01 baseline); fr has its own anchored table
    # (audit_resonance_fr.py / 2026-05-01 baseline); en still inherits zh.
    for lang in ("zh-CN", "zh", "Zh-CN", "ZH"):
        assert resonance_calibration.classify_zone(0.7, lang) == "mid_neutral"
    for lang in ("fr-FR", "fr"):
        assert resonance_calibration.classify_zone(0.7, lang) == "mid_neutral"
    for lang in ("en-US", "en"):
        assert resonance_calibration.classify_zone(0.7, lang) == "mid_neutral"
    # Unknown lang falls back to zh defaults — fail-safe for new locales.
    assert resonance_calibration.classify_zone(0.7, "xx-XX") == "mid_neutral"


def test_classify_zone_fr_specific_boundaries():
    # fr boundaries from tests/reports/fr_resonance_baseline_2026-05-01.md:
    # < 0.420 / 0.580 / 0.795 / 0.943.  These differ from zh enough to
    # produce visible misclassification at the corners — pin the diff.
    assert resonance_calibration.classify_zone(0.419, "fr") == "clearly_below_female"
    assert resonance_calibration.classify_zone(0.420, "fr") == "leans_male"
    assert resonance_calibration.classify_zone(0.579, "fr") == "leans_male"
    assert resonance_calibration.classify_zone(0.580, "fr") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.794, "fr") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.795, "fr") == "leans_female"
    assert resonance_calibration.classify_zone(0.942, "fr") == "leans_female"
    assert resonance_calibration.classify_zone(0.943, "fr") == "at_ceiling"
    # Cross-check: a value that's "mid_neutral" in zh but "at_ceiling" in fr
    # — proves the tables aren't aliased.
    assert resonance_calibration.classify_zone(0.95, "zh") == "leans_female"
    assert resonance_calibration.classify_zone(0.95, "fr") == "at_ceiling"


def test_classify_zone_none_inputs():
    # None / NaN / non-numeric → None (caller can pass through unguarded).
    assert resonance_calibration.classify_zone(None, "zh-CN") is None
    assert resonance_calibration.classify_zone(float("nan"), "zh-CN") is None
    assert resonance_calibration.classify_zone("not a number", "zh-CN") is None  # type: ignore[arg-type]


def test_zone_keys_low_to_high_consistency():
    # The exported tuple is the source of truth for advice_v2 / i18n key
    # generation.  If the order or set ever changes, this test pins which
    # callers need to update.
    assert resonance_calibration.ZONE_KEYS_LOW_TO_HIGH == (
        "clearly_below_female",
        "leans_male",
        "mid_neutral",
        "leans_female",
        "at_ceiling",
    )


# ── _aggregate_per_vowel — bucketing, filtering, ordering ───────────


def _phone(phone: str, *, z=(0.0, 0.0, 0.0), F=(400.0, 1500.0, 2500.0)) -> dict:
    """Helper — build a worker-side phone dict matching _build_phone_array
    output (start/end/char added for completeness; the aggregator ignores
    them but the test data should look representative)."""
    return {
        "start": 0.0,
        "end": 0.1,
        "char": "",
        "phone": phone,
        "pitch": None,
        "resonance": 0.5,
        "F1": F[0],
        "F2": F[1],
        "F3": F[2],
        "z_F1": z[0],
        "z_F2": z[1],
        "z_F3": z[2],
    }


def test_aggregate_empty_and_unknown_lang_noop():
    assert engine_c._aggregate_per_vowel([], "zh") == []
    # Unknown lang short → no-op (only zh / fr / en supported).
    assert engine_c._aggregate_per_vowel([_phone("a")], "xx") == []
    # Sub-MIN_TOKENS samples drop out per language.
    assert engine_c._aggregate_per_vowel([_phone("AA1", z=(0.1, 0.2, 0.3))], "en") == []
    assert engine_c._aggregate_per_vowel([_phone("a", z=(0.1, 0.2, 0.3))], "fr") == []


def test_aggregate_en_strips_stress_digits():
    # en sidecar emits ARPABET phones with stress digits (IY1 / IY2 / IY0
    # all = /i/ at different word positions).  After stripping the digit
    # they bucket into a single ``IY`` row.
    phones = [
        _phone("IY1", z=(-0.1, +0.5, +0.2), F=(380.0, 2500.0, 3100.0)),
        _phone("IY2", z=(-0.2, +0.4, +0.1), F=(375.0, 2480.0, 3050.0)),
        _phone("IY0", z=(-0.05, +0.6, +0.3), F=(390.0, 2550.0, 3120.0)),
        # Different stressed variant of /a/ (AA0/AA1) — must merge.
        _phone("AA1", z=(+0.4, +0.1, -0.2), F=(900.0, 1130.0, 2900.0)),
        _phone("AA0", z=(+0.5, +0.2, -0.1), F=(920.0, 1150.0, 2950.0)),
        _phone("AA2", z=(+0.3, 0.0, -0.3), F=(880.0, 1100.0, 2870.0)),
        # Consonants (no AEIOUY base, no stress digit) must be skipped.
        _phone("S", z=(0.1, 0.2, 0.3)),
        _phone("T", z=(0.0, 0.0, 0.0)),
    ]
    out = engine_c._aggregate_per_vowel(phones, "en")
    by_vowel = {r["vowel"]: r for r in out}
    assert set(by_vowel) == {"IY", "AA"}, f"got vowels {set(by_vowel)}"
    assert by_vowel["IY"]["n"] == 3
    assert by_vowel["IY"]["z_F2_med"] == 0.5  # median of {0.5, 0.4, 0.6}
    assert by_vowel["IY"]["F1_med_hz"] == 380
    assert by_vowel["AA"]["F1_med_hz"] == 900


def test_aggregate_en_drops_non_arpabet_vowels():
    # IPA-style ``i`` shouldn't accidentally bucket as ``IY`` (lowercase /
    # mismatch).  Same for fr-only nasal ``ɛ̃`` arriving on en path —
    # shouldn't appear in en output even with valid F-values.
    phones = [_phone("i", z=(0, 0, 0)) for _ in range(5)] + [
        _phone("ɛ̃", z=(0, 0, 0)) for _ in range(5)
    ]
    out = engine_c._aggregate_per_vowel(phones, "en")
    assert out == [], f"en path must reject non-ARPABET phones, got {out}"


def test_aggregate_zh_strips_tones_and_buckets():
    phones = [
        _phone("i˥", z=(-0.1, +0.5, +0.2), F=(380.0, 2500.0, 3100.0)),
        _phone("i˧", z=(-0.2, +0.4, +0.1), F=(375.0, 2480.0, 3050.0)),
        _phone("i˦", z=(-0.05, +0.6, +0.3), F=(390.0, 2550.0, 3120.0)),
        # Different vowel.
        _phone("a˥", z=(+0.4, +0.1, -0.2), F=(900.0, 1500.0, 2700.0)),
        _phone("a˨", z=(+0.5, +0.2, -0.1), F=(920.0, 1520.0, 2750.0)),
        _phone("a˧", z=(+0.3, 0.0, -0.3), F=(880.0, 1480.0, 2680.0)),
    ]
    out = engine_c._aggregate_per_vowel(phones, "zh")
    by_vowel = {r["vowel"]: r for r in out}
    assert set(by_vowel) == {"i", "a"}, "tone-stripping must merge i˥/i˧/i˦ → i"
    assert by_vowel["i"]["n"] == 3
    assert by_vowel["i"]["z_F2_med"] == 0.5  # median of {0.5, 0.4, 0.6}
    assert by_vowel["i"]["F1_med_hz"] == 380  # int, not 380.0
    assert by_vowel["a"]["F1_med_hz"] == 900


def test_aggregate_filters_consonants_and_sparse():
    phones = [
        # Consonant — not in _ZH_VOWELS, must be skipped even with valid F
        _phone("p", z=(0.1, 0.2, 0.3), F=(500.0, 1500.0, 2500.0)),
        # /y/ with only one observation — filtered by _PER_VOWEL_MIN_TOKENS=3
        _phone("y˥", z=(0.0, 0.3, 0.4), F=(350.0, 2200.0, 2800.0)),
        # /a/ with three valid observations — kept
        _phone("a˥", z=(+0.4, +0.1, -0.2), F=(900.0, 1500.0, 2700.0)),
        _phone("a˨", z=(+0.5, +0.2, -0.1), F=(920.0, 1520.0, 2750.0)),
        _phone("a˧", z=(+0.3, 0.0, -0.3), F=(880.0, 1480.0, 2680.0)),
    ]
    out = engine_c._aggregate_per_vowel(phones, "zh")
    assert [r["vowel"] for r in out] == ["a"]


def test_aggregate_sorts_by_descending_n():
    # Build buckets with different sizes and confirm output order is
    # n_desc — UI shows most-spoken vowels first.
    phones = []
    for _ in range(5):
        phones.append(_phone("a", z=(0, 0, 0), F=(900.0, 1500.0, 2500.0)))
    for _ in range(8):
        phones.append(_phone("i", z=(0, 0, 0), F=(380.0, 2500.0, 3100.0)))
    for _ in range(3):
        phones.append(_phone("u", z=(0, 0, 0), F=(400.0, 1000.0, 2600.0)))
    out = engine_c._aggregate_per_vowel(phones, "zh")
    assert [r["vowel"] for r in out] == ["i", "a", "u"]
    assert [r["n"] for r in out] == [8, 5, 3]


def test_aggregate_handles_none_z_values():
    # Real sidecar emits None for z_F1/z_F2/z_F3 when the formant tracker
    # had no signal for that frame (e.g. unvoiced consonants, outliers).
    # _aggregate_per_vowel must skip None values, not crash.
    phones = [
        _phone("i˥", z=(-0.1, +0.5, +0.2), F=(380.0, 2500.0, 3100.0)),
        # Mixed-None phone — z_F1 missing, others present.
        {**_phone("i˧"), "z_F1": None, "F1": None},
        # All-None phone — should not contribute n at all.
        {
            **_phone("i˦"),
            "z_F1": None,
            "z_F2": None,
            "z_F3": None,
            "F1": None,
            "F2": None,
            "F3": None,
        },
        _phone("i˥˥", z=(-0.05, +0.6, +0.3), F=(390.0, 2550.0, 3120.0)),
    ]
    out = engine_c._aggregate_per_vowel(phones, "zh")
    by_vowel = {r["vowel"]: r for r in out}
    # n is keyed off z_F1; the phone with z_F1=None doesn't contribute,
    # the one with all-None doesn't either → n=2, below MIN_TOKENS=3.
    # So /i/ must drop out of the output.
    assert "i" not in by_vowel, f"sparse z_F1 must drop the bucket, got {out}"


def test_aggregate_fr_uses_fr_inventory():
    # fr-only vowel /ɛ̃/ (nasal) — must be recognised so it appears in fr
    # output, but not in zh (where it isn't in _ZH_VOWELS).
    phones = [_phone("ɛ̃", z=(0.0, 0.0, 0.0)) for _ in range(4)]
    out_fr = engine_c._aggregate_per_vowel(phones, "fr")
    out_zh = engine_c._aggregate_per_vowel(phones, "zh")
    assert any(r["vowel"] == "ɛ̃" for r in out_fr)
    assert out_zh == []


# ── Runner ───────────────────────────────────────────────────────────


def _run_all() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(_run_all())
