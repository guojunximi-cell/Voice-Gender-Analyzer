"""Adaptive Praat formant-ceiling selector.

The vendored ``textgrid-formants.praat`` was originally hardcoded to a 5000 Hz
formant ceiling — Praat's recommended setting for adult MALE voices.  Adult
female voices have shorter vocal tracts and their upper formants (especially
F2 of high vowels like /i/, /y/, /e/) frequently sit above 5000 Hz; the LPC
fits 5 poles into a band missing the true F2, collapsing F1 + F2 into one
spurious peak and reporting a fake "F2" around 1300–1400 Hz instead of the
anatomically correct 2700–3000 Hz.  The downstream resonance score then
clamps to 0 (below 0.5 = "male" hue in the diverging palette), and a
clearly-female speaker reads as gender-ambiguous or male.

This module fixes that by extracting formants at five candidate ceilings
(4500 / 5000 / 5500 / 6000 / 6500 Hz) inside one Praat invocation and picking
per-recording the ceiling that minimises within-vowel-class formant variation
— the Escudero/Boersma 2009 heuristic, scaled down for short recordings.

Cooperates with the modified ``textgrid-formants.praat`` which emits a
``Multi-Ceiling-Formants:`` section after the standard ``Phonemes:`` section.

Public API:
  pick_best(praat_raw, lang) -> (chosen_ceiling_hz, rewritten_praat_text)
      rewritten_praat_text is byte-compatible with phones.parse(): it has the
      Phonemes: section's F1/F2/F3 columns replaced by the chosen ceiling's
      values, and the Multi-Ceiling-Formants: section dropped.

  parse_multi_ceiling(praat_raw) -> list[dict]
      Test/diagnostic helper.  Returns one dict per phone with keys
      {start, phone, F0, F1, F2, F3} where each F* is a 5-element list
      indexed by CEILINGS.

  CEILINGS — the candidate ceiling list (Hz), ordered low → high.
"""

from __future__ import annotations

import re
import statistics

# IPA tone diacritics (matches resonance._TONE_RE) — Mandarin phone labels carry
# them (e.g. "i˥˩"); strip before vowel-class membership so per-class CV
# aggregation isn't fragmented by tone variants.
_TONE_RE = re.compile(r"[˥˦˧˨˩]+")

# Candidate ceilings.  Range covers Praat's male (5000) and female (5500-6000)
# recommendations plus one bracket on either side.  The 5-step granularity is
# enough to land near-optimal without paying for finer search; per-recording
# CV scores are noisy at <500 Hz resolution anyway given typical 5–12 s clips.
CEILINGS = [4500, 5000, 5500, 6000, 6500]

# Selection parameters tuned on 200 male + 200 female fr CommonVoice clips
# (5–12 s).  Tightening MIN_TOKENS_PER_CLASS to 3 disqualified ~80% of clips
# (they don't yield 4 vowel classes with 3+ tokens each in 5 s).  Loosening
# below 2 tokens makes CV undefined.  These values keep the score statistically
# meaningful while qualifying ~95% of clips at this duration.
MIN_TOKENS_PER_CLASS = 2
MIN_VOWEL_CLASSES = 3

# F2 carries most of the gender signal (F1 = openness, F3 = lip rounding;
# F2 = tongue advancement + vocal-tract length).  F2 weighted 1.5×; F3 0.5×
# because it's noisier and less ceiling-sensitive.
F2_WEIGHT = 1.5
F3_WEIGHT = 0.5

# Vowel inventories — must match acousticgender.library.resonance.{ZH,FR}_VOWELS.
# Duplicated here (small constant set) to keep ceiling_selector free of vendor
# imports; both lists drift-guarded by tests/test_french_ceiling_selector.py.
_FR_VOWELS = {
    "a",
    "ɑ",
    "e",
    "ɛ",
    "i",
    "o",
    "ɔ",
    "u",
    "y",
    "ø",
    "œ",
    "ə",
    "ɛ̃",
    "ɑ̃",
    "ɔ̃",
    "œ̃",
}
_ZH_VOWELS = {
    "a",
    "aj",
    "aw",
    "e",
    "ej",
    "i",
    "io",
    "o",
    "ow",
    "u",
    "y",
    "ə",
    "ɥ",
    "ʐ̩",
    "z̩",
}

# Default when too few vowels qualify for a meaningful score (fr only — see
# _ADAPTIVE_LANGS below).  5500 Hz is Praat's official recommendation for adult
# female voices and works on most male voices too (slight female-color bias
# preferable to crashing accuracy on female voices, which is the bug we're
# fixing).
_DEFAULT_CEILING = 5500

# The legacy single-ceiling (which the vendored Praat script used to hardcode
# pre-2026-05-01) — used for languages NOT in _ADAPTIVE_LANGS so their stats
# files (calibrated against 5000 Hz extraction) keep reading correctly.
_LEGACY_CEILING = 5000

# Adaptive ceiling enabled for fr + zh.  Empirically:
#   - fr: female F2 of /i/ / /y/ / /e/ collapses at the 5000 Hz ceiling, so
#         adaptive ceiling lifts measurements out of clamp(0,1) floor and
#         restores gender separation (median 0.219 / 0.566 male/female,
#         gap +0.347).
#   - zh: same /i/ collapse at 5000 (female /i/ F2 1523 Hz vs literature
#         2700 = 56 % — see tests/reports/zh_resonance_baseline_2026-05-01).
#         Initially gated out because stats_zh.json was 5000 Hz-baked, which
#         caused over-correction on adaptive lift.  As of 2026-05-01 stats_zh
#         is re-trained at fixed 5500 Hz on AISHELL-3 (5000 segs, 50 phones)
#         so adaptive ceiling re-enabled here matches the new calibration.
#   - en: gender separation already acceptable at 5000 (median 0.49 / 0.89,
#         gap +0.40); selector picks ceiling per-recording across 4500–6500
#         and the existing 5m+5f regression doesn't drift.  Stays out of the
#         set for now — re-train stats.json @ 5500 to add it cleanly.
# en bypasses the selector entirely — the patched Praat script's Phonemes:
# section is still 5000 Hz baseline so phones.parse + resonance behaviour
# match pre-2026-05-01 byte-for-byte for languages outside the set.
_ADAPTIVE_LANGS = frozenset({"fr", "zh"})


def _is_vowel(phone: str | None, lang: str) -> bool:
    if not phone:
        return False
    if lang == "fr":
        return phone in _FR_VOWELS
    if lang == "zh":
        # Strip tone diacritics first — Mandarin phone labels carry them
        # (`i˥`, `a˧˨`), but ZH_VOWELS holds only the base nuclei.
        return _TONE_RE.sub("", phone) in _ZH_VOWELS
    return any(c in "AEIOUY" for c in phone)


def _f(s: str) -> float | None:
    if s in ("--undefined--", "", "?"):
        return None
    try:
        v = float(s)
    except (ValueError, TypeError):
        return None
    if v != v or v <= 0:
        return None
    return v


def parse_multi_ceiling(praat_raw: str) -> list[dict]:
    """Extract the per-phone × per-ceiling formant matrix from praat_raw.

    Returns a list of dicts with keys {start, phone, F0, F1, F2, F3} where each
    F-key holds a list of 5 floats (or None) indexed by CEILINGS.  Returns []
    when the section is absent or malformed (e.g. older Praat script that
    pre-dates the multi-ceiling patch).
    """
    rows: list[dict] = []
    in_multi = False
    for line in praat_raw.split("\n"):
        if line == "Multi-Ceiling-Formants:":
            in_multi = True
            continue
        if not in_multi:
            continue
        if line.startswith("#") or not line.strip():
            continue
        # Stop on next section header (mirrors phones.parse's section logic).
        if line.endswith(":") and "\t" not in line:
            break
        cols = line.split("\t")
        if len(cols) < 3 + 3 * len(CEILINGS):
            continue
        f1s, f2s, f3s = [], [], []
        for k in range(len(CEILINGS)):
            off = 3 + 3 * k
            f1s.append(_f(cols[off]))
            f2s.append(_f(cols[off + 1]))
            f3s.append(_f(cols[off + 2]))
        rows.append(
            {
                "start": _f(cols[0]),
                "phone": cols[1],
                "F0": _f(cols[2]),
                "F1": f1s,
                "F2": f2s,
                "F3": f3s,
            }
        )
    return rows


def _cv(values: list[float | None]) -> float | None:
    xs = [v for v in values if v and v > 0]
    if len(xs) < 2:
        return None
    med = statistics.median(xs)
    if med <= 0:
        return None
    return statistics.stdev(xs) / med


def score_ceiling(rows: list[dict], k: int, lang: str) -> float | None:
    """Mean per-vowel-class CV for ceiling index ``k``.  Lower = better.

    Returns ``None`` when fewer than MIN_VOWEL_CLASSES classes have at least
    MIN_TOKENS_PER_CLASS tokens — caller must fall back.
    """
    by_v: dict[str, list[tuple]] = {}
    for r in rows:
        if not _is_vowel(r["phone"], lang):
            continue
        by_v.setdefault(r["phone"], []).append((r["F1"][k], r["F2"][k], r["F3"][k]))
    good = {v: vs for v, vs in by_v.items() if len(vs) >= MIN_TOKENS_PER_CLASS}
    if len(good) < MIN_VOWEL_CLASSES:
        return None
    totals: list[float] = []
    for vs in good.values():
        cv1 = _cv([t[0] for t in vs]) or 0
        cv2 = _cv([t[1] for t in vs]) or 0
        cv3 = _cv([t[2] for t in vs]) or 0
        totals.append(cv1 + F2_WEIGHT * cv2 + F3_WEIGHT * cv3)
    return statistics.mean(totals)


def _rewrite_with_ceiling(praat_raw: str, rows: list[dict], k: int) -> str:
    """Rebuild praat_raw with the Phonemes: section's F1/F2/F3 replaced by
    ceiling-k values, and the Multi-Ceiling-Formants: section dropped.

    Output is byte-compatible with the pre-patch Praat script — phones.parse()
    consumes it without modification.
    """
    rows_by_key: dict[tuple, dict] = {}
    for r in rows:
        key = (round(r["start"], 4) if r["start"] is not None else None, r["phone"])
        rows_by_key[key] = r

    out_lines: list[str] = []
    section: str | None = None
    for line in praat_raw.split("\n"):
        if line == "Words:" or line == "Phonemes:":
            section = line[:-1]
            out_lines.append(line)
            continue
        if line == "Multi-Ceiling-Formants:":
            break  # drop the rest
        if section == "Phonemes":
            cols = line.split("\t")
            if len(cols) >= 6:
                start = _f(cols[0])
                key = (round(start, 4) if start is not None else None, cols[1])
                match = rows_by_key.get(key)
                if match:
                    f1, f2, f3 = match["F1"][k], match["F2"][k], match["F3"][k]
                    f1s = "--undefined--" if f1 is None else repr(f1)
                    f2s = "--undefined--" if f2 is None else repr(f2)
                    f3s = "--undefined--" if f3 is None else repr(f3)
                    line = "\t".join([cols[0], cols[1], cols[2], f1s, f2s, f3s])
        out_lines.append(line)
    return "\n".join(out_lines)


def rewrite_to_ceiling(praat_raw: str, ceiling_hz: int) -> str:
    """Rewrite ``praat_raw`` so its ``Phonemes:`` section reflects
    ``ceiling_hz`` (must be one of ``CEILINGS``).  Used by training scripts
    that need a fixed ceiling instead of the per-recording CV-min pick.

    No-ops (returns ``praat_raw`` unchanged) when the multi-ceiling section
    is missing or the requested ceiling isn't in ``CEILINGS``.
    """
    if ceiling_hz not in CEILINGS:
        return praat_raw
    rows = parse_multi_ceiling(praat_raw)
    if not rows:
        return praat_raw
    return _rewrite_with_ceiling(praat_raw, rows, CEILINGS.index(ceiling_hz))


def pick_best(praat_raw: str, lang: str) -> tuple[int, str]:
    """Pick the optimal ceiling for ``praat_raw`` and rewrite the Phonemes:
    section to use that ceiling's formants.

    Returns ``(chosen_ceiling_hz, rewritten_praat_text)``.  When the multi-
    ceiling section is missing or insufficient data for scoring, returns
    ``(_DEFAULT_CEILING, praat_raw)`` unchanged so callers can pipeline this
    through phones.parse() without a special case.

    Languages not in ``_ADAPTIVE_LANGS`` are pinned to the legacy 5000 Hz
    ceiling — see ``_ADAPTIVE_LANGS`` docstring for the data behind that gate.
    The patched Praat script still emits its standard ``Phonemes:`` section at
    5000 Hz, so for those languages we return the input unchanged and
    phones.parse / compute_resonance keep their pre-patch behaviour.
    """
    if lang not in _ADAPTIVE_LANGS:
        return _LEGACY_CEILING, praat_raw

    rows = parse_multi_ceiling(praat_raw)
    if not rows:
        return _DEFAULT_CEILING, praat_raw

    scores = [score_ceiling(rows, k, lang) for k in range(len(CEILINGS))]
    valid = [(s, k) for k, s in enumerate(scores) if s is not None]
    if not valid:
        chosen_k = CEILINGS.index(_DEFAULT_CEILING)
    else:
        best = min(s for s, _ in valid)
        # Tie-tolerance 5%: if multiple ceilings score within 5% of the
        # minimum, prefer the one closest to the centre of the candidate
        # list — avoids picking edge ceilings on flat-score recordings
        # where the search has no real preference.
        near = [k for s, k in valid if s <= best * 1.05]
        mid = len(CEILINGS) // 2
        chosen_k = sorted(near, key=lambda k: abs(k - mid))[0]
    return CEILINGS[chosen_k], _rewrite_with_ceiling(praat_raw, rows, chosen_k)
