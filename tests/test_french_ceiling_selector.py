"""Standalone tests for voiceya/sidecars/wrapper/ceiling_selector.py.

Two layers:
  1. Pure-logic unit tests on synthesised multi-ceiling Praat output:
       - per-class CV score is minimum at the ceiling whose formants cluster.
       - tie-tolerance picks the middle ceiling when scores are flat.
       - empty / under-populated input falls back to default 5500 Hz.

  2. Cached-fixture regression on 4 male + 4 female fr CommonVoice clips
     (multi-ceiling Praat output text checked into tests/fixtures/...).
     For each fixture:
       - selector.pick_best returns the snapshotted ceiling.
       - re-running phones.parse + resonance.compute_resonance on the
         rewritten Praat text yields a median resonance within ±0.05 of
         the snapshot.
     Aggregate across the 8 fixtures:
       - median(female chosen ceilings) > median(male chosen ceilings)
       - median(female adaptive medians) > median(male adaptive medians)

Run: ``python tests/test_french_ceiling_selector.py``  (no pytest needed).
"""

from __future__ import annotations

import json
import os
import pathlib
import statistics
import sys
import traceback

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "voiceya", "sidecars", "wrapper"))
sys.path.insert(0, os.path.join(REPO, "voiceya", "sidecars", "visualizer-backend"))

# phones.parse + resonance.compute_resonance read stats_fr.json /
# weights_fr.json / french_mfa_dict.txt via bare relative paths — chdir into
# the visualizer-backend dir like the sidecar's WORKDIR=/app does in prod.
_PRIOR_CWD = os.getcwd()
os.chdir(os.path.join(REPO, "voiceya", "sidecars", "visualizer-backend"))

import acousticgender.library.phones as phones  # noqa: E402
import acousticgender.library.resonance as resonance  # noqa: E402
import ceiling_selector  # noqa: E402

with open("weights_fr.json") as _f:
    _WEIGHTS_FR = json.load(_f)

FIX_DIR = pathlib.Path(REPO) / "tests" / "fixtures" / "ceiling_selector"


# ── Synthetic builders ──────────────────────────────────────────────────


def _build_synthetic_multi(rows: list[tuple[str, list[tuple[float, float, float]]]]) -> str:
    """Build a Praat-style multi-ceiling section from per-phone formants.

    rows: list of (phone, [(F1@C0, F2@C0, F3@C0), ..., (F1@C4, F2@C4, F3@C4)]).
          Length of inner list MUST equal len(CEILINGS).
    """
    lines = ["Words:", "0\t", "Phonemes:"]
    # Standard Phonemes section — uses ceiling index 1 (5000 Hz) like the
    # patched Praat script; selector ignores it but phones.parse() will read
    # the rewritten version.
    for i, (phone, ceil_rows) in enumerate(rows):
        f1, f2, f3 = ceil_rows[1]
        lines.append(f"{0.1 * i}\t{phone}\t150\t{f1}\t{f2}\t{f3}")
    lines.append("Multi-Ceiling-Formants:")
    lines.append(f"# ceilings: {' '.join(str(c) for c in ceiling_selector.CEILINGS)}")
    for i, (phone, ceil_rows) in enumerate(rows):
        assert len(ceil_rows) == len(ceiling_selector.CEILINGS)
        row = [f"{0.1 * i}", phone, "150"]
        for f1, f2, f3 in ceil_rows:
            row += [f"{f1}", f"{f2}", f"{f3}"]
        lines.append("\t".join(row))
    return "\n".join(lines)


# ── Unit tests ──────────────────────────────────────────────────────────


def _clustering_at_5500_rows():
    """Builder for the 'best ceiling = 5500' synthetic.  Within-token CV is
    zero at ceiling 5500 and grows away from it on either side, so the score
    (mean per-class CV) has a strict minimum at index 2.
    """
    rows = []
    for cls, base_f2 in [("a", 1500.0), ("i", 2700.0), ("e", 2000.0), ("u", 900.0)]:
        for tok in range(3):
            # `tok` is the within-class token index.  The deviation from
            # base_f2 at each ceiling = (tok-1) × ceiling-specific magnitude;
            # magnitude is 0 at index 2 (perfect cluster) and rises both ways.
            scale = [200.0, 100.0, 0.0, 100.0, 250.0]
            ceil_rows = []
            for k, mag in enumerate(scale):
                f1 = 400 + 30 * (tok - 1)  # always-noisy F1
                f2 = base_f2 + mag * (tok - 1)
                f3 = 2400 + 40 * (tok - 1)
                ceil_rows.append((f1, f2, f3))
            rows.append((cls, ceil_rows))
    return rows


def test_score_minimum_at_clustering_ceiling():
    rows = _clustering_at_5500_rows()
    raw = _build_synthetic_multi(rows)
    parsed = ceiling_selector.parse_multi_ceiling(raw)
    assert len(parsed) == 12, f"expected 12 phones, got {len(parsed)}"
    scores = [
        ceiling_selector.score_ceiling(parsed, k, "fr")
        for k in range(len(ceiling_selector.CEILINGS))
    ]
    assert all(s is not None for s in scores), f"some scores None: {scores}"
    min_idx = min(range(len(scores)), key=lambda k: scores[k])
    assert min_idx == 2, f"expected min at 5500 (idx 2), got idx {min_idx}, scores={scores}"


def test_pick_best_returns_clustering_ceiling():
    raw = _build_synthetic_multi(_clustering_at_5500_rows())
    chosen, rewritten = ceiling_selector.pick_best(raw, "fr")
    assert chosen == 5500, f"expected 5500, got {chosen}"
    # Rewritten output must drop Multi-Ceiling-Formants section.
    assert "Multi-Ceiling-Formants:" not in rewritten


def test_pick_best_tie_breaker_prefers_middle():
    # Build a flat-score recording: all ceilings give identical formants per
    # class.  Tie-tolerance (5%) should pick the middle ceiling (5500).
    rows = []
    for cls, base_f2 in [("a", 1500.0), ("i", 2700.0), ("e", 2000.0), ("u", 900.0)]:
        for _ in range(2):
            ceil_rows = [(400, base_f2, 2400)] * 5
            rows.append((cls, ceil_rows))
    raw = _build_synthetic_multi(rows)
    chosen, _ = ceiling_selector.pick_best(raw, "fr")
    assert chosen == 5500, f"flat score should pick middle (5500), got {chosen}"


def test_pick_best_falls_back_on_empty():
    chosen, rewritten = ceiling_selector.pick_best("Words:\n0\t\nPhonemes:\n", "fr")
    assert chosen == 5500, f"empty multi section should default to 5500, got {chosen}"


def test_pick_best_falls_back_on_too_few_vowels():
    # Only 1 vowel class with 2 tokens — fails MIN_VOWEL_CLASSES (3).
    rows = [
        ("a", [(400, 1500, 2400)] * 5),
        ("a", [(400, 1500, 2400)] * 5),
    ]
    raw = _build_synthetic_multi(rows)
    chosen, _ = ceiling_selector.pick_best(raw, "fr")
    assert chosen == 5500, f"too-few-vowels should default to 5500, got {chosen}"


def test_parse_multi_ceiling_handles_undefined():
    # Praat emits "--undefined--" for unvoiced phones.  parse_multi_ceiling
    # must convert these to None without crashing.
    row = "0.5\ts\t--undefined--\t--undefined--\t--undefined--\t--undefined--\t800\t1900\t2700\t820\t1950\t2800\t830\t1970\t2820\t850\t2000\t2850\t860\t2050\t2900"
    raw = "Words:\n0\t\nPhonemes:\nMulti-Ceiling-Formants:\n" + row
    parsed = ceiling_selector.parse_multi_ceiling(raw)
    assert len(parsed) == 1
    assert parsed[0]["phone"] == "s"
    assert parsed[0]["F1"][0] is None  # 4500 was --undefined--
    assert parsed[0]["F1"][1] == 800.0  # 5000 had value


# ── Fixture regression ──────────────────────────────────────────────────


def _resonance_for(praat_text: str) -> tuple[int, list[float]]:
    """Return (chosen_ceiling, list of per-phone resonance values for non-sil
    non-sp phones with computed resonance).

    phones.parse and resonance.compute_resonance read french_mfa_dict.txt /
    stats_fr.json with bare relative paths.  stats_fr.json lives in the
    visualizer-backend cwd we already chdir'd into; french_mfa_dict.txt is
    a 4 MB MFA download that's NOT vendored in repo, so we keep a stub
    covering only the words present in fixtures next to the fixtures and
    chdir there for the duration of the call.
    """
    chosen, rewritten = ceiling_selector.pick_best(praat_text, "fr")
    prev_cwd = os.getcwd()
    # Stage french_mfa_dict.txt + stats_fr.json side by side so phones.parse
    # (reads dict by relative path) and resonance.compute_resonance (reads
    # stats_fr.json by relative path) both succeed in one cwd.
    os.chdir(FIX_DIR)
    # stats_fr.json + weights_fr.json live in visualizer-backend; symlink
    # lazily so we keep one cwd switch.  No-op if the symlinks exist.
    for fname in ("stats_fr.json", "weights_fr.json"):
        dst = FIX_DIR / fname
        if not dst.exists():
            os.symlink(
                os.path.join(REPO, "voiceya", "sidecars", "visualizer-backend", fname),
                dst,
            )
    try:
        data = phones.parse(rewritten, lang="fr")
        resonance.compute_resonance(data, _WEIGHTS_FR, lang="fr")
    finally:
        os.chdir(prev_cwd)
    res = [
        p["resonance"]
        for p in data["phones"]
        if p.get("resonance") is not None and p.get("phoneme") not in (None, "", "sil", "sp")
    ]
    return chosen, res


def _load_expected() -> dict:
    with open(FIX_DIR / "expected.json") as f:
        return json.load(f)


def test_fixtures_chosen_ceiling_matches_snapshot():
    expected = _load_expected()
    mismatches = []
    for tag, exp in expected.items():
        raw = (FIX_DIR / f"{tag}.praat.txt").read_text()
        chosen, _ = _resonance_for(raw)
        if chosen != exp["chosen_ceiling_hz"]:
            mismatches.append(f"{tag}: expected {exp['chosen_ceiling_hz']}, got {chosen}")
    assert not mismatches, "ceiling drift:\n  " + "\n  ".join(mismatches)


def test_fixtures_median_resonance_within_tolerance():
    expected = _load_expected()
    tol = 0.05
    mismatches = []
    for tag, exp in expected.items():
        raw = (FIX_DIR / f"{tag}.praat.txt").read_text()
        _, res = _resonance_for(raw)
        assert res, f"{tag}: empty resonance list"
        got = statistics.median(res)
        want = exp["median_resonance_adaptive"]
        if abs(got - want) > tol:
            mismatches.append(f"{tag}: expected {want:.3f}±{tol}, got {got:.3f}")
    assert not mismatches, "resonance drift:\n  " + "\n  ".join(mismatches)


def test_aggregate_gender_separation():
    expected = _load_expected()
    by_gender_chosen: dict[str, list[int]] = {"male": [], "female": []}
    by_gender_median: dict[str, list[float]] = {"male": [], "female": []}
    for tag, exp in expected.items():
        raw = (FIX_DIR / f"{tag}.praat.txt").read_text()
        chosen, res = _resonance_for(raw)
        by_gender_chosen[exp["gender"]].append(chosen)
        by_gender_median[exp["gender"]].append(statistics.median(res))

    med_ceil_male = statistics.median(by_gender_chosen["male"])
    med_ceil_female = statistics.median(by_gender_chosen["female"])
    assert med_ceil_female > med_ceil_male, (
        f"selector should pick higher ceilings for female speakers; "
        f"got male median {med_ceil_male} Hz vs female median {med_ceil_female} Hz"
    )

    med_res_male = statistics.median(by_gender_median["male"])
    med_res_female = statistics.median(by_gender_median["female"])
    assert med_res_female > med_res_male, (
        f"after adaptive ceiling, female median resonance should exceed male; "
        f"got male {med_res_male:.3f} vs female {med_res_female:.3f}"
    )


def test_drift_guard_vowel_inventory():
    # ceiling_selector duplicates FR_VOWELS / ZH_VOWELS from resonance.py to
    # stay free of vendor imports.  This guard catches divergence on any
    # upstream-resonance update.
    from acousticgender.library.resonance import FR_VOWELS, ZH_VOWELS

    assert ceiling_selector._FR_VOWELS == FR_VOWELS, "FR_VOWELS drift"
    assert ceiling_selector._ZH_VOWELS == ZH_VOWELS, "ZH_VOWELS drift"


def test_en_bypasses_adaptive():
    # As of 2026-05-01 zh joined `_ADAPTIVE_LANGS` (stats_zh.json re-trained
    # at 5500 Hz on AISHELL-3 — see scripts/train_stats_zh.py).  Only en is
    # still pinned to 5000 because stats.json (cmudict baseline) hasn't been
    # re-trained yet.  Use one of the fr fixtures (with a healthy
    # Multi-Ceiling-Formants section) so we know the bypass happens because
    # of language, not because data is missing.
    raw = (FIX_DIR / "f1_female_c5000.praat.txt").read_text()
    chosen, rewritten = ceiling_selector.pick_best(raw, "en")
    assert chosen == 5000, f"en: expected 5000 (legacy bypass), got {chosen}"
    assert rewritten == raw, "en: praat_raw should be returned unchanged"


def test_zh_uses_adaptive_picker():
    # zh: same fr fixture must now go through the CV-min picker since zh
    # entered _ADAPTIVE_LANGS.  Selector is permitted to land on any of
    # CEILINGS but must not return the legacy 5000 bypass shape (where
    # rewritten == raw).
    raw = (FIX_DIR / "f1_female_c5000.praat.txt").read_text()
    chosen, rewritten = ceiling_selector.pick_best(raw, "zh")
    assert chosen in ceiling_selector.CEILINGS
    assert rewritten != raw, "zh: rewritten praat should differ from input"
    assert "Multi-Ceiling-Formants:" not in rewritten


def test_zh_tone_stripping_in_is_vowel():
    # Mandarin phone labels carry IPA tone diacritics.  _is_vowel must strip
    # those before checking ZH_VOWELS membership; without this guard the zh
    # selector returns 0 vowel classes per recording and silently falls back
    # to default (the bug we observed in the e2e ablation).
    assert ceiling_selector._is_vowel("i˥", "zh") is True
    assert ceiling_selector._is_vowel("a˧˨", "zh") is True
    assert ceiling_selector._is_vowel("i", "zh") is True  # untoned still works
    assert ceiling_selector._is_vowel("k", "zh") is False  # consonant


# ── Driver ──────────────────────────────────────────────────────────────


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception:
            failures += 1
            print(f"  ERROR {t.__name__}:")
            print(traceback.format_exc())
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    # Restore cwd in case caller chains tests.
    os.chdir(_PRIOR_CWD)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
