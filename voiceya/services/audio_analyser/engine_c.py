"""Engine C orchestrator — 进阶声学分析.

工作流：
    1. 按 language 选 ASR：zh-CN 走 FunASR Paraformer-zh，en-US 走 faster-whisper；
       script 模式跳过 ASR，直接用前端传来的稿子。
    2. 把 {audio, transcript, language} POST 给 visualizer-backend sidecar
    3. sidecar 跑 ffmpeg → SoX 降噪 → MFA 对齐（mandarin_mfa 或 english_mfa）
       → Praat 共振峰 → 音素级 z-score
    4. 返回段聚合后的 pitch/resonance 数据，合入 summary.engine_c

设计边界：
    * 永不抛异常——任何失败都落到 summary.engine_c = None，主响应正常返回。
    * feature flag ENGINE_C_ENABLED=False 时连 ASR 都不 import。
    * Engine C 在 Engine B 之后跑，等 seg 结果就位；整段音频上跑一次
      （不按 VAD 段切），避免短段对齐失败。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Literal

from voiceya.config import CFG
from voiceya.services.audio_analyser import resonance_calibration

if TYPE_CHECKING:
    from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem

logger = logging.getLogger(__name__)

# Mandarin 每个汉字≈2 音素（声母+韵母），英文每个词≈3-4 个 ARPABET 音素，
# 法语每个词≈2.5-3 个 IPA 音素（联诵 + 不发音尾辅音让平均值偏低）。
# phone_ratio 低于阈值表示 MFA 只对齐到零星几个音素，多半是用户漏读/跑题。
_LOW_PHONE_RATIO_ZH = 0.8  # phones / hanzi
_LOW_PHONE_RATIO_EN = 1.5  # phones / word token
_LOW_PHONE_RATIO_FR = 1.5  # phones / word token — 起步同英文，跑通 baseline 后再调
# 韩语每个 Hangul 音节 ≈ 2-3 phones（初声+中声+可选终声）；起步抄 en/fr，
# calibration_v1 跑完后再调。Hangul 音节而非 eojeol（更接近 zh 数 hanzi 的语义）。
_LOW_PHONE_RATIO_KO = 1.5  # phones / Hangul syllable
# 对齐的音素区间 / 音频总时长；低于 30% 一般意味着用户只读了开头几秒就停了。
_LOW_COVERAGE_THRESHOLD = 0.3
# 匹配单个汉字（BMP 范围够用；扩展 A/B 区等生僻字几乎不会进日常脚本）。
_HAN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
# \u5339\u914d Hangul \u97f3\u8282\u5757\uff08U+AC00\u2013U+D7A3\uff0c11 172 \u4e2a\u9884\u7ec4\u5408\u97f3\u8282\uff0c\u8986\u76d6\u73b0\u4ee3\u97e9\u6587 100%\uff09\u3002
# \u4e0d\u5339\u914d Jamo\uff08U+1100\u2013U+11FF\uff09\u2014 \u73b0\u4ee3\u6b63\u5b57\u6cd5\u90fd\u7528\u9884\u7ec4\u5408\u5f62\u5f0f\uff0cJamo \u4e3b\u8981\u51fa\u73b0\u5728
# \u53e4\u6587\u732e\u6216\u952e\u76d8\u8f93\u5165\u4e2d\u95f4\u6001\uff0cASR \u8f93\u51fa\u548c MFA \u5b57\u5178\u90fd\u4e0d\u4f1a\u7528\u3002
_HANGUL_SYLL_RE = re.compile(r"[\uac00-\ud7a3]")

# IPA tone diacritics (matches resonance.py / ceiling_selector.py).  Mandarin
# phone labels carry them (i\u02e5\u02e9, a\u02e5\u02e5); strip before bucketing so per-vowel
# aggregation isn't fragmented by tone variants \u2014 tones colour F0, not F1/F2.
_TONE_RE = re.compile(r"[\u02e5-\u02e9]+")

# Vowel inventories per language \u2014 must match the vendored
# acousticgender/library/resonance.py {ZH,FR}_VOWELS.  Worker-side copy here
# because resonance.py only runs in the sidecar process.  en uses ARPABET
# (cmudict / english_us_arpa) \u2014 see _EN_VOWELS + _ARPABET_STRESS_RE below.
_ZH_VOWELS: frozenset[str] = frozenset(
    {
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
        "\u0259",
        "\u0265",
        "\u0290\u0329",
        "z\u0329",
    }
)
_FR_VOWELS: frozenset[str] = frozenset(
    {
        "a",
        "\u0251",
        "e",
        "\u025b",
        "i",
        "o",
        "\u0254",
        "u",
        "y",
        "\u00f8",
        "\u0153",
        "\u0259",
        "\u025b\u0303",
        "\u0251\u0303",
        "\u0254\u0303",
        "\u0153\u0303",
    }
)
# Korean MFA v3 vowel nuclei \u2014 must mirror sidecar's resonance.KO_VOWELS and
# ceiling_selector._KO_VOWELS.  7 base monophthongs \u00d7 short/long + \u0250 (no
# long variant), 15 labels total.  Glides (j, w, \u0270, \u0265) excluded \u2014
# Korean diphthongs emit as glide+vowel sequences.  Modern Seoul collapse
# already applied upstream (no \u00f8 / y in the v3 phone set).  Length mark
# is \u02d0 (\u02d0).  Inventory verified against
# `mfa model inspect acoustic korean_mfa`.
_KO_VOWELS: frozenset[str] = frozenset(
    {
        "\u0250",
        "e",
        "e\u02d0",
        "\u025b",
        "\u025b\u02d0",
        "i",
        "i\u02d0",
        "o",
        "o\u02d0",
        "u",
        "u\u02d0",
        "\u0268",
        "\u0268\u02d0",
        "\u028c",
        "\u028c\u02d0",
    }
)
# ARPABET vowel base classes (cmudict / english_us_arpa).  The MFA sidecar
# emits stress-digited variants like ``IY1`` / ``AH0`` / ``EH2`` \u2014 strip the
# trailing 0/1/2 before set membership.  No tone diacritics; en is single
# accent (cmudict General American).
_EN_VOWELS: frozenset[str] = frozenset(
    {
        "AA",
        "AE",
        "AH",
        "AO",
        "AW",
        "AY",
        "EH",
        "ER",
        "EY",
        "IH",
        "IY",
        "OW",
        "OY",
        "UH",
        "UW",
    }
)
# ARPABET stress-digit suffix.  ``IY1.rstrip("012") == "IY"`` would do, but a
# regex makes the intent explicit and matches scripts/audit_resonance_en.py.
_ARPABET_STRESS_RE = re.compile(r"[012]$")
# Per-phone guidance is suppressed below this many tokens \u2014 single-digit
# samples make medians too noisy to act on (one mis-aligned phone can swing
# z_F2_med by 0.5 \u03c3).  Lowered 3\u21922 (2026-05-08) so 30 s recordings surface
# more long-tail vowels + sonorant consonants; advice_v2._WEAKNESS_MIN_TOKENS
# moved in lockstep.  n=2 still gives a "min-of-two" robustness; UI
# annotates each row with (n=X) so users can judge reliability.
_PER_VOWEL_MIN_TOKENS = 2

# language 归一化：前端/上游传 BCP-47 形式（zh-CN、en-US），sidecar / 调度用短码。
_LANG_SHORT: dict[str, str] = {
    "zh-CN": "zh",
    "zh": "zh",
    "en-US": "en",
    "en": "en",
    "fr-FR": "fr",
    "fr": "fr",
    "ko-KR": "ko",
    "ko": "ko",
}


def _normalize_lang(language: str) -> str:
    """BCP-47 → short ("zh"/"en"); unknown → "zh" (fail-safe to current default)."""
    return _LANG_SHORT.get(language, "zh")


def _should_skip(analyse_results: "list[AnalyseResultItem]") -> str | None:
    """Return skip-reason (str) or None if Engine C should run.

    Caller is responsible for checking engine_c_enabled before calling
    run_engine_c; this function only validates runtime conditions.
    """
    voiced = sum(r.duration for r in analyse_results if r.label in ("female", "male"))
    if voiced < CFG.engine_c_min_duration_sec:
        return f"voiced={voiced:.1f}s < min={CFG.engine_c_min_duration_sec}s"

    return None


async def run_engine_c(
    audio_bytes: bytes,
    analyse_results: "list[AnalyseResultItem]",
    *,
    mode: Literal["free", "script"] = "free",
    script: str | None = None,
    language: str = "zh-CN",
) -> dict[str, Any] | None:
    """Run Engine C on the full audio buffer.

    Returns the engine_c summary dict, or None on skip / failure.

    ``mode="script"`` bypasses the ASR pass and feeds ``script`` straight to
    MFA — saves 2-5 s + the ASR model RAM footprint, and gives MFA a clean
    ground-truth transcript instead of whatever ASR guessed.

    ``language`` (BCP-47: ``zh-CN`` / ``en-US``) picks which ASR backend to
    invoke in free mode and which asset set the sidecar loads.
    """
    skip_reason = _should_skip(analyse_results)
    if skip_reason:
        logger.info("Engine C skipped: %s", skip_reason)
        return None

    lang_short = _normalize_lang(language)

    # word_timestamps feeds the sidecar's parallel-chunking path (en free mode
    # only for now).  None → sidecar falls back to its single-block MFA pipeline.
    word_timestamps: list[dict] | None = None

    if mode == "script":
        transcript = (script or "").strip()
        if not transcript:
            logger.info("Engine C skipped: script mode with empty script")
            return None
    else:
        # Deferred imports — keep module-load time near zero when feature is off
        # (ASR is the biggest hit; only pay it for free-speech mode).
        try:
            import httpx  # noqa: PLC0415

            if lang_short == "en":
                from voiceya.services.audio_analyser.engine_c_asr_en import (  # noqa: PLC0415
                    transcribe_en,
                )
            elif lang_short == "fr":
                from voiceya.services.audio_analyser.engine_c_asr_fr import (  # noqa: PLC0415
                    transcribe_fr,
                )
            elif lang_short == "ko":
                from voiceya.services.audio_analyser.engine_c_asr_ko import (  # noqa: PLC0415
                    transcribe_ko,
                )
            else:
                from voiceya.services.audio_analyser.engine_c_asr import (  # noqa: PLC0415
                    transcribe_zh,
                )
        except ImportError as exc:
            logger.warning("Engine C dependencies missing (install `engine-c` group): %s", exc)
            return None

        try:
            if lang_short == "en":
                transcript, word_timestamps = await transcribe_en(audio_bytes)
            elif lang_short == "fr":
                transcript, word_timestamps = await transcribe_fr(audio_bytes)
            elif lang_short == "ko":
                transcript, word_timestamps = await transcribe_ko(audio_bytes)
            else:
                transcript = await transcribe_zh(audio_bytes)
        except Exception as exc:  # defensive — _transcribe itself swallows errors
            logger.warning("Engine C ASR raised unexpectedly: %s", exc)
            return None

        if not transcript.strip():
            logger.info("Engine C skipped: empty transcript (noise / non-speech)")
            return None

    # httpx is needed in both branches — import here so script mode also has it.
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:
        logger.warning("Engine C dependencies missing (install `engine-c` group): %s", exc)
        return None

    headers: dict[str, str] = {}
    if CFG.engine_c_sidecar_token:
        headers["X-Engine-C-Token"] = CFG.engine_c_sidecar_token

    post_data: dict[str, str] = {"transcript": transcript, "language": language}
    if word_timestamps:
        # JSON-encode so multipart/form-data stays flat.  Sidecar parses back
        # to list[dict]; malformed payloads are ignored on that side.
        post_data["word_timestamps_json"] = json.dumps(word_timestamps)

    try:
        async with httpx.AsyncClient(timeout=CFG.engine_c_sidecar_timeout_sec) as client:
            resp = await client.post(
                f"{CFG.engine_c_sidecar_url}/engine_c/analyze",
                files={"audio": ("audio.wav", audio_bytes, "audio/wav")},
                data=post_data,
                headers=headers,
            )
        if resp.status_code != 200:
            logger.warning(
                "Engine C sidecar returned %d: %s",
                resp.status_code,
                resp.text[:300],
            )
            return None
        data = resp.json()
    except Exception as exc:
        logger.warning("Engine C sidecar call failed: %s", exc)
        return None

    # 源 resonance.py 可能因样本不足而不填某些字段；全部按 None-safe 取。
    raw_phones = data.get("phones") or []
    phones = _build_phone_array(raw_phones, data.get("words") or [], lang_short)

    # Silence ranges come from ffmpeg silencedetect (-30 dB, 0.5s min) run
    # in the sidecar wrapper alongside MFA.  The frontend uses them as the
    # authoritative sentence-break signal — more reliable than inferring
    # pauses from phone-to-phone gaps (Praat writes every phone's end = next
    # phone's start, so phone gaps are always ~0 even across real silences).
    raw_silence = data.get("silenceRanges") or []
    silence_ranges = [
        {"start": s, "end": e}
        for s, e in (
            (_safe_float(r.get("start")), _safe_float(r.get("end")))
            for r in raw_silence
            if isinstance(r, dict)
        )
        if s is not None and e is not None and e > s
    ]

    total_audio_sec = sum(r.duration for r in analyse_results)
    alignment_confidence = _alignment_confidence(phones, transcript, total_audio_sec, lang_short)

    median_resonance = _safe_float(data.get("medianResonance"))

    # Zone classification uses median-of-per-vowel-medians (each vowel weighs
    # equally, regardless of how many times it appeared) so a frequent
    # low-resonance vowel can't drag the speaker out of an otherwise-feminine
    # zone. Falls back to the sidecar's flat-list median when no vowel meets
    # the n ≥ 5 threshold (very short / vowel-imbalanced recordings).
    per_vowel_data = _aggregate_per_vowel(phones, lang_short)
    qualifying_meds = [
        float(v["resonance_med"])
        for v in per_vowel_data
        if (v.get("n") or 0) >= 5 and isinstance(v.get("resonance_med"), (int, float))
    ]
    zone_median = _median(qualifying_meds) if qualifying_meds else median_resonance

    summary = {
        "mean_pitch_hz": _safe_float(data.get("meanPitch")),
        "median_pitch_hz": _safe_float(data.get("medianPitch")),
        "stdev_pitch_hz": _safe_float(data.get("stdevPitch")),
        "mean_resonance": _safe_float(data.get("meanResonance")),
        "median_resonance": median_resonance,
        "stdev_resonance": _safe_float(data.get("stdevResonance")),
        "phone_count": len(phones),
        "word_count": len(data.get("words") or []),
        "transcript": transcript,
        "phones": phones,
        "silence_ranges": silence_ranges,
        "mode": mode,
        "script": script if mode == "script" else None,
        "language": language,
        "alignment_confidence": alignment_confidence,
        # Adaptive Praat formant ceiling chosen by the sidecar's
        # ceiling_selector (per-recording, in Hz).  None means one of:
        #   (a) sidecar predates the 2026-05-01 multi-ceiling Praat patch
        #       and the field isn't in the response,
        #   (b) sidecar produced zero Praat TSVs (alignment empty), or
        #   (c) MFA produced zero chunks → merge bypassed.
        # en-US still pins to legacy 5000 because stats.json hasn't been
        # re-trained at 5500 Hz yet.  Frontend / advice consumers must
        # treat this as opt-in telemetry, not a gate.
        "formant_ceiling_hz": _safe_int(data.get("formant_ceiling_hz")),
        # Phase C surface — interpretation layer for advice_v2 / UI.  Both
        # are advisory; the raw `median_resonance` and per-phone `phones`
        # array remain authoritative for any consumer that wants to ignore
        # the binning.
        "resonance_zone_key": resonance_calibration.classify_zone(zone_median, language),
        "resonance_per_vowel": per_vowel_data,
    }

    # INFO 不带用户解析数值（pitch / resonance / 对齐分数 / phone 数量都是结果指纹），
    # 只留 lang+mode 两个低基数标签；详情下放 DEBUG。
    logger.info("Engine C done — lang=%s mode=%s", language, mode)
    logger.debug(
        "Engine C done detail — %d phones, mean_pitch=%s Hz, mean_resonance=%s, align=%s",
        summary["phone_count"],
        summary["mean_pitch_hz"],
        summary["mean_resonance"],
        alignment_confidence,
    )
    return summary


def _alignment_confidence(
    phones: list[dict[str, Any]],
    transcript: str,
    total_audio_sec: float,
    lang_short: str,
) -> dict[str, Any]:
    """Compute soft quality signals for the MFA alignment.

    ``phone_ratio``: aligned phones per transcript token.  Mandarin counts
    hanzi (~1.5-2.5 phones each, threshold 0.8); English counts whitespace-
    split words (~3-4 ARPABET phones each, threshold 1.5).  Low ratios mean
    MFA only picked up fragments — user skipped words, misread in script
    mode, or ASR hallucinated text that had no audio backing.

    ``coverage``: aligned phone span / total audio duration — low coverage
    means most of the audio is silence or un-aligned.

    ``low_quality``: boolean hint for the UI banner.  Kept loose — this is a
    "heads up" signal, not a hard error.
    """
    if lang_short == "en":
        token_count = len(transcript.split())
        low_ratio_threshold = _LOW_PHONE_RATIO_EN
    elif lang_short == "fr":
        token_count = len(transcript.split())
        low_ratio_threshold = _LOW_PHONE_RATIO_FR
    elif lang_short == "ko":
        # Hangul syllables (NOT eojeol/words) — semantics close to how zh
        # counts hanzi.  ASR cleanup strips Latin / digits so transcript is
        # syllable-only; .findall over the syllable block is exact.
        token_count = len(_HANGUL_SYLL_RE.findall(transcript))
        low_ratio_threshold = _LOW_PHONE_RATIO_KO
    else:
        token_count = len(_HAN_CHAR_RE.findall(transcript))
        low_ratio_threshold = _LOW_PHONE_RATIO_ZH
    phone_ratio: float | None = None
    if token_count > 0:
        phone_ratio = len(phones) / token_count

    coverage: float | None = None
    if phones and total_audio_sec > 0:
        first_start = min((p["start"] for p in phones), default=0.0)
        last_end = max((p["end"] for p in phones), default=0.0)
        span = max(0.0, last_end - first_start)
        coverage = min(1.0, span / total_audio_sec)

    low_quality = False
    if phone_ratio is not None and phone_ratio < low_ratio_threshold:
        low_quality = True
    if coverage is not None and coverage < _LOW_COVERAGE_THRESHOLD:
        low_quality = True

    return {
        "phone_ratio": round(phone_ratio, 3) if phone_ratio is not None else None,
        "coverage": round(coverage, 3) if coverage is not None else None,
        "low_quality": low_quality,
    }


def _phone_is_vowel(label: str, lang_short: str) -> bool:
    """Whether ``label`` is a vowel in ``lang_short``'s inventory.

    Mirrors the normalization in ``_aggregate_per_vowel`` — zh strips IPA
    tone diacritics, en strips ARPABET stress digits.  Used both per-phone
    (so the frontend can filter by vowel-ness without duplicating the
    inventory) and per-aggregate (the bucket's flag).
    """
    if not label or lang_short not in ("zh", "fr", "en"):
        return False
    if lang_short == "zh":
        return _TONE_RE.sub("", label) in _ZH_VOWELS
    if lang_short == "fr":
        return label in _FR_VOWELS
    # en
    return _ARPABET_STRESS_RE.sub("", label) in _EN_VOWELS


def _build_phone_array(
    raw_phones: list[dict[str, Any]],
    words: list[dict[str, Any]],
    lang_short: str,
) -> list[dict[str, Any]]:
    """Transform sidecar phone dicts into the frontend-facing format.

    Each raw phone has ``time`` (start) but no explicit end — the end is
    the next phone's start time.  We also map each phone back to its hanzi
    character via the ``word_index`` cross-reference.

    ``is_vowel`` is computed against the language's vowel inventory so the
    frontend's resonance classifier (classify.js) can filter consonants in
    the 共鸣 tab when the user toggles "仅元音", without duplicating the
    vowel sets across stacks.
    """
    if not raw_phones:
        return []

    phones: list[dict[str, Any]] = []
    for i, p in enumerate(raw_phones):
        start = _safe_float(p.get("time"))
        if start is None:
            continue

        # End time = next phone's start, or for the last phone, start + 0.1 s
        if i + 1 < len(raw_phones):
            end = _safe_float(raw_phones[i + 1].get("time"))
            if end is None or end <= start:
                end = start + 0.1
        else:
            end = start + 0.1

        # Map to hanzi via word_index → words[idx]["word"]
        word_idx = p.get("word_index")
        char = ""
        if word_idx is not None and 0 <= word_idx < len(words):
            char = words[word_idx].get("word", "") or ""

        formants = p.get("F") or []
        # F_stdevs from the sidecar are z-scores relative to the
        # female reference distribution (resonance.compute_resonance line
        # 64-69).  Surfaced as z_F1/z_F2/z_F3 so the worker / advice layer
        # can do per-vowel guidance without re-reading stats files.  None
        # for consonants whose phoneme isn't in stats[expected].
        f_stdevs = p.get("F_stdevs") or []
        phone_label = p.get("phoneme", "")
        phones.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "char": char,
                "phone": phone_label,
                "is_vowel": _phone_is_vowel(phone_label, lang_short),
                "pitch": _safe_float(formants[0]) if len(formants) > 0 else None,
                "resonance": _safe_float(p.get("resonance")),
                "F1": _safe_float(formants[1]) if len(formants) > 1 else None,
                "F2": _safe_float(formants[2]) if len(formants) > 2 else None,
                "F3": _safe_float(formants[3]) if len(formants) > 3 else None,
                "z_F1": _safe_float(f_stdevs[1]) if len(f_stdevs) > 1 else None,
                "z_F2": _safe_float(f_stdevs[2]) if len(f_stdevs) > 2 else None,
                "z_F3": _safe_float(f_stdevs[3]) if len(f_stdevs) > 3 else None,
            }
        )

    return phones


def _aggregate_per_vowel(
    phones: list[dict[str, Any]],
    lang_short: str,
) -> list[dict[str, Any]]:
    """Bucket scored phones by phoneme label, return per-class medians.

    Naming kept as ``_aggregate_per_vowel`` (and field ``resonance_per_vowel``)
    for schema continuity, but as of 2026-05-08 we no longer filter to the
    ``_ZH/EN/FR_VOWELS`` set — any phone the sidecar attached a ``resonance``
    score to is bucketed.  Sonorants (/m/, /n/, /j/, /w/, /l/, …) carry real
    vocal-tract resonance information; obstruents are ones the sidecar
    typically can't score (no F-stdevs → no resonance).  Each entry now
    carries ``is_vowel`` so downstream layers can keep weakness coaching
    vowel-only while letting the UI display all phones.

    Phase A baseline (2026-05-01) showed the clamped resonance score loses
    diagnostic power on most vowels (sat_rate > 50 % for /a / aw / aj /…).
    The raw F-vector z-scores still carry signal below the clamp, so
    advice_v2 uses this aggregate to drive per-phone display + coaching.

    Output shape::

        [{"vowel": "i", "n": 22, "is_vowel": True,
          "z_F1_med": -0.05, "z_F2_med": +0.10, "z_F3_med": -0.20,
          "F1_med_hz": 380, "F2_med_hz": 2520, "F3_med_hz": 3100,
          "resonance_med": 0.71}, ...]

    Sorted by descending sample count so the UI naturally surfaces the
    most-spoken phone classes first.  Phones with fewer than
    ``_PER_VOWEL_MIN_TOKENS`` tokens are dropped (medians too noisy).

    en uses ARPABET phone labels with stress digits (``IY1``, ``AH0``); the
    digits are stripped before bucketing so all stress variants of a vowel
    aggregate together.  Consonants in ARPABET have no stress digit, so the
    regex is a no-op for them.  zh strips IPA tone diacritics — also a no-op
    for tone-less consonants.
    """
    if not phones or lang_short not in ("zh", "fr", "en", "ko"):
        return []
    if lang_short == "zh":
        vowel_set = _ZH_VOWELS
        normalize = _TONE_RE.sub
    elif lang_short == "fr":
        vowel_set = _FR_VOWELS
        normalize = lambda _r, p: p  # noqa: E731 — short identity for the dispatcher  # type: ignore[assignment]
    elif lang_short == "ko":
        # Korean MFA v3 emits phone labels in raw IPA — no tone marks, no
        # stress digits, no normalisation needed.  Short/long are separate
        # phones in KO_VOWELS, so they aggregate into separate buckets.
        vowel_set = _KO_VOWELS
        normalize = lambda _r, p: p  # noqa: E731 — short identity  # type: ignore[assignment]
    else:  # en
        vowel_set = _EN_VOWELS
        normalize = _ARPABET_STRESS_RE.sub  # type: ignore[assignment]

    buckets: dict[str, dict[str, list[float]]] = {}
    for p in phones:
        raw_label = p.get("phone") or ""
        if not raw_label:
            continue
        # Skip phones the sidecar couldn't score — without a resonance value
        # the row carries no signal worth aggregating.
        if p.get("resonance") is None:
            continue
        label = normalize("", raw_label) if lang_short in ("zh", "en") else raw_label
        bucket = buckets.setdefault(
            label,
            {"z_F1": [], "z_F2": [], "z_F3": [], "F1": [], "F2": [], "F3": [], "resonance": []},
        )
        for key in ("z_F1", "z_F2", "z_F3", "F1", "F2", "F3", "resonance"):
            v = p.get(key)
            if v is not None:
                bucket[key].append(float(v))

    out: list[dict[str, Any]] = []
    for label, b in buckets.items():
        n = len(b["resonance"])
        if n < _PER_VOWEL_MIN_TOKENS:
            continue
        out.append(
            {
                "vowel": label,
                "n": n,
                "is_vowel": label in vowel_set,
                "z_F1_med": _round_or_none(_median(b["z_F1"]), 3),
                "z_F2_med": _round_or_none(_median(b["z_F2"]), 3),
                "z_F3_med": _round_or_none(_median(b["z_F3"]), 3),
                "F1_med_hz": _round_or_none(_median(b["F1"]), 0),
                "F2_med_hz": _round_or_none(_median(b["F2"]), 0),
                "F3_med_hz": _round_or_none(_median(b["F3"]), 0),
                # Per-phone resonance score (0-1, same scale as the panel-level
                # median_resonance). advice_v2 uses this to drive the simple
                # good/low/weak classification that replaced the F-axis logic.
                "resonance_med": _round_or_none(_median(b["resonance"]), 3),
            }
        )
    out.sort(key=lambda r: -r["n"])
    return out


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def _round_or_none(x: float | None, ndigits: int) -> float | int | None:
    if x is None:
        return None
    r = round(x, ndigits)
    # ndigits=0 returns float in py3 — cast to int so JSON stays compact
    # for Hz fields ("F1_med_hz": 380 not 380.0).
    return int(r) if ndigits == 0 else r


def _safe_float(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(x: Any) -> int | None:
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None
