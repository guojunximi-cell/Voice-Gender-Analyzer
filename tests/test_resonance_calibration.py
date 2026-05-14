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
    # (audit_resonance_fr.py / 2026-05-01 baseline); en got its own table
    # 2026-05-05 (LibriSpeech audit) — no longer aliases zh; ko bootstrap-
    # aliases to fr (2026-05-12) until calibration_v1 ko data lands.
    for lang in ("zh-CN", "zh", "Zh-CN", "ZH"):
        assert resonance_calibration.classify_zone(0.7, lang) == "mid_neutral"
    for lang in ("fr-FR", "fr"):
        assert resonance_calibration.classify_zone(0.7, lang) == "mid_neutral"
    for lang in ("en-US", "en"):
        assert resonance_calibration.classify_zone(0.7, lang) == "mid_neutral"
    for lang in ("ko-KR", "ko"):
        assert resonance_calibration.classify_zone(0.7, lang) == "mid_neutral"
    # Unknown lang falls back to zh defaults — fail-safe for new locales.
    assert resonance_calibration.classify_zone(0.7, "xx-XX") == "mid_neutral"


def test_classify_zone_en_specific_boundaries():
    # en boundaries from tests/reports/calibration_v1/aggregate.csv (2026-05-06):
    # F P5=0.525, P25=0.689, P75=0.987 (clamped to AT_CEILING=0.98).  These
    # differ from zh enough to produce visible misclassification at the
    # corners — pin the diff so en never silently re-aliases zh.  Note:
    # en's leans_female zone is empty by construction (mid_neutral upper =
    # AT_CEILING = leans_female upper) since 26% of cis-female en speakers
    # already saturate at the meter ceiling.
    assert resonance_calibration.classify_zone(0.524, "en") == "clearly_below_female"
    assert resonance_calibration.classify_zone(0.525, "en") == "leans_male"
    assert resonance_calibration.classify_zone(0.688, "en") == "leans_male"
    assert resonance_calibration.classify_zone(0.689, "en") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.92, "en") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.979, "en") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.98, "en") == "at_ceiling"
    assert resonance_calibration.classify_zone(0.99, "en") == "at_ceiling"
    # Cross-check: a value that's "leans_female" in zh is still "mid_neutral"
    # in en — proves the tables aren't aliased.
    assert resonance_calibration.classify_zone(0.85, "zh") == "leans_female"
    assert resonance_calibration.classify_zone(0.85, "en") == "mid_neutral"


def test_classify_zone_ko_aliases_fr_until_measured():
    # ko is bootstrap-aliased to fr percentiles (resonance_calibration.py
    # 2026-05-12 — _ZONES_KO = _ZONES_FR).  Pin this so a future calibration
    # update unaliases ko explicitly + this test forces the update.
    test_points = [0.40, 0.50, 0.65, 0.85, 0.95]
    for v in test_points:
        ko = resonance_calibration.classify_zone(v, "ko-KR")
        fr = resonance_calibration.classify_zone(v, "fr-FR")
        assert ko == fr, f"ko ({ko}) ≠ fr ({fr}) at v={v} — alias broke?"


def test_mid_neutral_falls_inside_typical_female_range():
    """``mid_neutral`` is the F P25..P75 band — i.e. half of real cis-female
    speakers sit here.  This regression test exists because the pre-2026-05-05
    summary copy ("still some distance from the female reference") directly
    contradicted that fact.  If anyone repurposes ``mid_neutral`` as a
    non-female zone, they MUST also update web/src/modules/i18n.js so we
    don't reintroduce the contradiction."""
    # zh: P25-P75 = 0.612-0.842
    assert resonance_calibration.classify_zone(0.65, "zh-CN") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.83, "zh-CN") == "mid_neutral"
    # en (calibration_v1): P25-P75 = 0.689-0.98 (P75 clamped to ceiling)
    assert resonance_calibration.classify_zone(0.70, "en-US") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.92, "en-US") == "mid_neutral"
    # fr (calibration_v1): P25-P75 = 0.547-0.752
    assert resonance_calibration.classify_zone(0.60, "fr-FR") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.74, "fr-FR") == "mid_neutral"
    # ko (aliased to fr): same P25-P75 band as fr
    assert resonance_calibration.classify_zone(0.60, "ko-KR") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.74, "ko-KR") == "mid_neutral"


def test_classify_zone_fr_specific_boundaries():
    # fr boundaries from tests/reports/calibration_v1/aggregate.csv (2026-05-06):
    # < 0.430 / 0.547 / 0.752 / 0.960.  Drift from 2026-05-01 v17 baseline:
    # P25 -0.033 and P75 -0.043 (90 spk × 11 stitched clips) — meaningful
    # shifts toward male side.
    assert resonance_calibration.classify_zone(0.429, "fr") == "clearly_below_female"
    assert resonance_calibration.classify_zone(0.430, "fr") == "leans_male"
    assert resonance_calibration.classify_zone(0.546, "fr") == "leans_male"
    assert resonance_calibration.classify_zone(0.547, "fr") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.751, "fr") == "mid_neutral"
    assert resonance_calibration.classify_zone(0.752, "fr") == "leans_female"
    assert resonance_calibration.classify_zone(0.959, "fr") == "leans_female"
    assert resonance_calibration.classify_zone(0.960, "fr") == "at_ceiling"
    # Cross-check: a value that's "mid_neutral" in zh but "at_ceiling" in fr
    # — proves the tables aren't aliased.
    assert resonance_calibration.classify_zone(0.97, "zh") == "leans_female"
    assert resonance_calibration.classify_zone(0.97, "fr") == "at_ceiling"


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
    # Unknown lang short → no-op (only zh / fr / en / ko supported).
    assert engine_c._aggregate_per_vowel([_phone("a")], "xx") == []
    # Sub-MIN_TOKENS samples drop out per language.
    assert engine_c._aggregate_per_vowel([_phone("AA1", z=(0.1, 0.2, 0.3))], "en") == []
    assert engine_c._aggregate_per_vowel([_phone("a", z=(0.1, 0.2, 0.3))], "fr") == []
    assert engine_c._aggregate_per_vowel([_phone("ɐ", z=(0.1, 0.2, 0.3))], "ko") == []


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


def test_aggregate_ko_uses_ko_inventory():
    # ko vowels: ɐ (Korean /a/, NOT plain "a"), short/long pairs (e/eː etc).
    # Plain ASCII "a" must be REJECTED on ko path (no fr-style fallback)
    # since MFA korean_mfa emits /ɐ/ for that nucleus.
    ko_phones = [
        _phone("ɐ", z=(0, 0, 0), F=(900.0, 1400.0, 2700.0)),
        _phone("ɐ", z=(0.1, 0.05, -0.05), F=(880.0, 1380.0, 2680.0)),
        _phone("ɐ", z=(-0.1, 0.1, 0.05), F=(910.0, 1420.0, 2720.0)),
        # Short + long /i/ — separate buckets per length contrast.
        _phone("i", z=(-0.2, 0.5, 0.3), F=(380.0, 2500.0, 3100.0)),
        _phone("i", z=(-0.15, 0.45, 0.25), F=(375.0, 2480.0, 3080.0)),
        _phone("iː", z=(-0.25, 0.55, 0.35), F=(370.0, 2520.0, 3120.0)),
        _phone("iː", z=(-0.18, 0.50, 0.28), F=(382.0, 2510.0, 3110.0)),
        # /ɨ/ Korean /ㅡ/ — never in fr/zh/en inventories.
        _phone("ɨ", z=(0.1, -0.2, -0.3), F=(420.0, 1280.0, 2600.0)),
        _phone("ɨ", z=(0.0, -0.25, -0.35), F=(415.0, 1290.0, 2620.0)),
        # Plain ASCII "a" must be rejected — MFA emits "ɐ" instead.
        _phone("a", z=(0, 0, 0)),
        _phone("a", z=(0, 0, 0)),
        # Glide /j/ — semi-vowel, not in KO_VOWELS, rejected.
        _phone("j", z=(0, 0, 0)),
        _phone("j", z=(0, 0, 0)),
        _phone("j", z=(0, 0, 0)),
    ]
    out = engine_c._aggregate_per_vowel(ko_phones, "ko")
    vowels = {r["vowel"] for r in out}
    # /ɐ/ has n=3 → kept; short /i/ has n=2 → dropped; long /iː/ has n=2 → dropped;
    # /ɨ/ has n=2 → dropped.  Plain "a" + /j/ never bucket because they're not
    # in _KO_VOWELS.
    assert vowels == {"ɐ"}, f"ko ko-only bucketing failed: {vowels}"
    # Cross-lang check: ko phones run through fr path must NOT bucket /ɐ/
    # (since it's not in _FR_VOWELS — fr has plain /a/ instead).
    out_fr = engine_c._aggregate_per_vowel(ko_phones, "fr")
    assert all(r["vowel"] != "ɐ" for r in out_fr), "ɐ leaked into fr inventory"


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
