from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from voiceya.config import CFG
from voiceya.services.audio_analyser.audio_tools import normalize_audio_for_analysis
from voiceya.services.audio_analyser.engine_a import do_segmentation
from voiceya.services.audio_analyser.engine_c import run_engine_c
from voiceya.services.audio_analyser.seg_analyser import do_analyse_segments
from voiceya.services.audio_analyser.statics import do_statics
from voiceya.services.sse import ProgressSSE

if TYPE_CHECKING:
    from io import BytesIO

    from voiceya.services.events_stream import PublisherT

logger = logging.getLogger(__name__)


async def do_analyse(content: BytesIO, publish: PublisherT):
    """Async generator: yields SSE event strings with real progress, last event has type='result'."""
    sample = await normalize_audio_for_analysis(content, publish)

    # ── Engine A: 时间分段 ─────────────────────────────────
    logger.info("Engine A 分析中…")
    await publish(ProgressSSE(pct=10, msg="鸭鸭正在聆听声纹…（此步骤较慢）"))

    segmentation_results = await do_segmentation(sample)

    # ── Engine B: 声学分析（仅对有声语音段）────────────
    await publish(ProgressSSE(pct=50, msg="鸭鸭听完了！正在整理笔记…"))

    sample.seek(0)
    # 开 Engine C 时给"开小灶"阶段留一大段进度预算（72→94）——它是最慢的一环，
    # 进度太靠右会让用户以为马上就好，其实还要等 ASR + MFA + Praat 跑完。
    seg_end_pct = 70 if CFG.engine_c_enabled else 95
    analyse_results = await do_analyse_segments(
        sample, segmentation_results, publish, end_pct=seg_end_pct
    )

    # ── Engine C: 进阶分析（feature-flagged，默认关）────────
    engine_c_summary = None
    if CFG.engine_c_enabled:
        await publish(ProgressSSE(pct=72, msg="鸭鸭开小灶做进阶分析…"))
        sample.seek(0)
        audio_bytes = sample.read()
        engine_c_summary = await run_engine_c(audio_bytes, analyse_results)

    # ── 全局汇总统计 ───────────────────────────────────────
    await publish(ProgressSSE(pct=98, msg="鸭鸭快好了…"))

    result = do_statics(analyse_results)
    summary = result["summary"]
    summary["engine_c"] = engine_c_summary
    logger.info(
        "分析完成 — %d 段，F0=%s Hz，性别评分=%s，女性占比=%.3f，Engine C=%s",
        len(analyse_results),
        summary["overall_f0_median_hz"],
        summary["overall_gender_score"],
        summary["female_ratio"],
        "on" if engine_c_summary else "off/skip",
    )

    result["filename"] = "upload"

    return result
