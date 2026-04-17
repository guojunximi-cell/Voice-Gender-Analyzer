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
from typing import TYPE_CHECKING, Any

from voiceya.config import CFG

if TYPE_CHECKING:
    from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem

logger = logging.getLogger(__name__)


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
) -> dict[str, Any] | None:
    """Run Engine C on the full audio buffer.

    Returns the engine_c summary dict, or None on skip / failure.
    """
    skip_reason = _should_skip(analyse_results)
    if skip_reason:
        logger.info("Engine C skipped: %s", skip_reason)
        return None

    # Deferred imports — keep module-load time near zero when feature is off.
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

    try:
        async with httpx.AsyncClient(timeout=CFG.engine_c_sidecar_timeout_sec) as client:
            resp = await client.post(
                f"{CFG.engine_c_sidecar_url}/engine_c/analyze",
                files={"audio": ("audio.wav", audio_bytes, "audio/wav")},
                data={"transcript": transcript},
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
    summary = {
        "mean_pitch_hz": _safe_float(data.get("meanPitch")),
        "median_pitch_hz": _safe_float(data.get("medianPitch")),
        "stdev_pitch_hz": _safe_float(data.get("stdevPitch")),
        "mean_resonance": _safe_float(data.get("meanResonance")),
        "median_resonance": _safe_float(data.get("medianResonance")),
        "stdev_resonance": _safe_float(data.get("stdevResonance")),
        "phone_count": len(data.get("phones") or []),
        "word_count": len(data.get("words") or []),
        "transcript": transcript,
    }

    logger.info(
        "Engine C done — %d phones, mean_pitch=%s Hz, mean_resonance=%s",
        summary["phone_count"],
        summary["mean_pitch_hz"],
        summary["mean_resonance"],
    )
    return summary


def _safe_float(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None
