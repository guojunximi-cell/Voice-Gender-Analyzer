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
# 对齐的音素区间 / 音频总时长；低于 30% 一般意味着用户只读了开头几秒就停了。
_LOW_COVERAGE_THRESHOLD = 0.3
# 匹配单个汉字（BMP 范围够用；扩展 A/B 区等生僻字几乎不会进日常脚本）。
_HAN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")

# IPA tone diacritics (matches resonance.py / ceiling_selector.py).  Mandarin
# phone labels carry them (i\u02e5\u02e9, a\u02e5\u02e5); strip before bucketing so per-vowel
# aggregation isn't fragmented by tone variants \u2014 tones colour F0, not F1/F2.
_TONE_RE = re.compile(r"[\u02e5-\u02e9]+")

# Vowel inventories per language \u2014 must match the vendored
# acousticgender/library/resonance.py {ZH,FR}_VOWELS.  Worker-side copy here
# because resonance.py only runs in the sidecar process.  English keeps the
# vendored heuristic ("any phone token containing AEIOUY") because cmudict
# uses ARPABET phones (AA, IY, EH, etc.) that don't fit a flat set cleanly.
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
# Per-vowel guidance is suppressed below this many tokens \u2014 single-digit
# samples make medians too noisy to act on (one mis-aligned phone can swing
# z_F2_med by 0.5 \u03c3).  Picked to roughly match the sidecar's >2 \u03c3 outlier
# trim convention.
_PER_VOWEL_MIN_TOKENS = 3

# language 归一化：前端/上游传 BCP-47 形式（zh-CN、en-US），sidecar / 调度用短码。
_LANG_SHORT: dict[str, str] = {
    "zh-CN": "zh",
    "zh": "zh",
    "en-US": "en",
    "en": "en",
    "fr-FR": "fr",
    "fr": "fr",
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
    phones = _build_phone_array(raw_phones, data.get("words") or [])

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
        "resonance_zone_key": resonance_calibration.classify_zone(median_resonance, language),
        "resonance_per_vowel": _aggregate_per_vowel(phones, lang_short),
    }

    logger.info(
        "Engine C done — lang=%s mode=%s, %d phones, mean_pitch=%s Hz, mean_resonance=%s, align=%s",
        language,
        mode,
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


def _build_phone_array(
    raw_phones: list[dict[str, Any]],
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Transform sidecar phone dicts into the frontend-facing format.

    Each raw phone has ``time`` (start) but no explicit end — the end is
    the next phone's start time.  We also map each phone back to its hanzi
    character via the ``word_index`` cross-reference.
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
        phones.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "char": char,
                "phone": p.get("phoneme", ""),
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
    """Bucket phones by vowel class, return per-class median z + Hz medians.

    Phase A baseline (2026-05-01) showed the clamped resonance score loses
    diagnostic power on most vowels (sat_rate > 50 % for /a / aw / aj /…).
    The raw F-vector z-scores still carry signal below the clamp, so
    advice_v2 will use this aggregate to drive per-vowel coaching.

    Output shape::

        [{"vowel": "i", "n": 22,
          "z_F1_med": -0.05, "z_F2_med": +0.10, "z_F3_med": -0.20,
          "F1_med_hz": 380, "F2_med_hz": 2520, "F3_med_hz": 3100}, ...]

    Sorted by descending sample count so the UI can naturally surface the
    most-spoken vowel classes first.  Vowels with fewer than
    ``_PER_VOWEL_MIN_TOKENS`` tokens are dropped (medians too noisy).

    en is intentionally a no-op for now: its ARPABET phone inventory and
    pre-Phase-B stats.json calibration mean per-vowel medians wouldn't be
    interpretable next to fr / zh.  Returns ``[]`` for en.
    """
    if not phones or lang_short not in ("zh", "fr"):
        return []
    vowel_set = _ZH_VOWELS if lang_short == "zh" else _FR_VOWELS

    buckets: dict[str, dict[str, list[float]]] = {}
    for p in phones:
        raw_label = p.get("phone") or ""
        label = _TONE_RE.sub("", raw_label) if lang_short == "zh" else raw_label
        if label not in vowel_set:
            continue
        bucket = buckets.setdefault(
            label,
            {"z_F1": [], "z_F2": [], "z_F3": [], "F1": [], "F2": [], "F3": []},
        )
        for key in ("z_F1", "z_F2", "z_F3", "F1", "F2", "F3"):
            v = p.get(key)
            if v is not None:
                bucket[key].append(float(v))

    out: list[dict[str, Any]] = []
    for vowel, b in buckets.items():
        n = len(b["z_F1"])
        if n < _PER_VOWEL_MIN_TOKENS:
            continue
        out.append(
            {
                "vowel": vowel,
                "n": n,
                "z_F1_med": _round_or_none(_median(b["z_F1"]), 3),
                "z_F2_med": _round_or_none(_median(b["z_F2"]), 3),
                "z_F3_med": _round_or_none(_median(b["z_F3"]), 3),
                "F1_med_hz": _round_or_none(_median(b["F1"]), 0),
                "F2_med_hz": _round_or_none(_median(b["F2"]), 0),
                "F3_med_hz": _round_or_none(_median(b["F3"]), 0),
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
