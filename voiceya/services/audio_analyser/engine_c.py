"""Engine C orchestrator — 进阶声学分析.

工作流：
    1. FunASR Paraformer-zh 把音频转成中文 transcript
    2. 把 {audio, transcript} POST 给 visualizer-backend sidecar
    3. sidecar 跑 ffmpeg → SoX 降噪 → MFA 对齐 → Praat 共振峰 → 音素级 z-score
    4. 返回段聚合后的 pitch/resonance 数据，合入 summary.engine_c

设计边界：
    * 永不抛异常——任何失败都落到 summary.engine_c = None，主响应正常返回。
    * feature flag ENGINE_C_ENABLED=False 时连 FunASR 都不 import。
    * Engine C 在 Engine B 之后跑，等 seg 结果就位；整段音频上跑一次
      （不按 VAD 段切），避免短段对齐失败。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Literal

from voiceya.config import CFG

if TYPE_CHECKING:
    from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem

logger = logging.getLogger(__name__)

# Mandarin 每个汉字≈2 音素（声母+韵母）；phone_ratio 远低于 1 表示 MFA 只对齐到零星
# 几个音素，很可能是用户漏读/跑题。用 0.8 留点余地（尾声母有时被合并）。
_LOW_PHONE_RATIO_THRESHOLD = 0.8
# 对齐的音素区间 / 音频总时长；低于 30% 一般意味着用户只读了开头几秒就停了。
_LOW_COVERAGE_THRESHOLD = 0.3
# 匹配单个汉字（BMP 范围够用；扩展 A/B 区等生僻字几乎不会进日常脚本）。
_HAN_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


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
) -> dict[str, Any] | None:
    """Run Engine C on the full audio buffer.

    Returns the engine_c summary dict, or None on skip / failure.

    ``mode="script"`` bypasses the FunASR pass and feeds ``script`` straight
    to MFA — saves 2-5 s + the Paraformer RAM footprint, and gives MFA a
    clean ground-truth transcript instead of whatever ASR guessed.
    """
    skip_reason = _should_skip(analyse_results)
    if skip_reason:
        logger.info("Engine C skipped: %s", skip_reason)
        return None

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

            from voiceya.services.audio_analyser.engine_c_asr import transcribe_zh  # noqa: PLC0415
        except ImportError as exc:
            logger.warning("Engine C dependencies missing (install `engine-c` group): %s", exc)
            return None

        try:
            transcript = await transcribe_zh(audio_bytes)
        except Exception as exc:  # defensive — transcribe_zh itself swallows errors
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

    try:
        async with httpx.AsyncClient(timeout=CFG.engine_c_sidecar_timeout_sec) as client:
            resp = await client.post(
                f"{CFG.engine_c_sidecar_url}/engine_c/analyze",
                files={"audio": ("audio.wav", audio_bytes, "audio/wav")},
                data={"transcript": transcript},
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
    alignment_confidence = _alignment_confidence(phones, transcript, total_audio_sec)

    summary = {
        "mean_pitch_hz": _safe_float(data.get("meanPitch")),
        "median_pitch_hz": _safe_float(data.get("medianPitch")),
        "stdev_pitch_hz": _safe_float(data.get("stdevPitch")),
        "mean_resonance": _safe_float(data.get("meanResonance")),
        "median_resonance": _safe_float(data.get("medianResonance")),
        "stdev_resonance": _safe_float(data.get("stdevResonance")),
        "phone_count": len(phones),
        "word_count": len(data.get("words") or []),
        "transcript": transcript,
        "phones": phones,
        "silence_ranges": silence_ranges,
        "mode": mode,
        "script": script if mode == "script" else None,
        "alignment_confidence": alignment_confidence,
    }

    logger.info(
        "Engine C done — mode=%s, %d phones, mean_pitch=%s Hz, mean_resonance=%s, align=%s",
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
) -> dict[str, Any]:
    """Compute soft quality signals for the MFA alignment.

    ``phone_ratio``: aligned phones / hanzi in transcript — Mandarin typically
    runs 1.5-2.5 phones per hanzi, so < ~0.8 suggests MFA only picked up
    fragments (user skipped words / misread in script mode, or ASR hallucinated
    characters that had no audio in free mode).

    ``coverage``: aligned phone span / total audio duration — low coverage
    means most of the audio is silence or un-aligned.

    ``low_quality``: boolean hint for the UI banner.  Kept loose — this is a
    "heads up" signal, not a hard error.
    """
    han_count = len(_HAN_CHAR_RE.findall(transcript))
    phone_ratio: float | None = None
    if han_count > 0:
        phone_ratio = len(phones) / han_count

    coverage: float | None = None
    if phones and total_audio_sec > 0:
        first_start = min((p["start"] for p in phones), default=0.0)
        last_end = max((p["end"] for p in phones), default=0.0)
        span = max(0.0, last_end - first_start)
        coverage = min(1.0, span / total_audio_sec)

    low_quality = False
    if phone_ratio is not None and phone_ratio < _LOW_PHONE_RATIO_THRESHOLD:
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
            }
        )

    return phones


def _safe_float(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None
