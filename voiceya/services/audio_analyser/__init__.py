import logging
from typing import TYPE_CHECKING

from voiceya.services.audio_analyser.auto_tools import prepare_audio_for_analysis
from voiceya.services.audio_analyser.engine_a import do_segmentation
from voiceya.services.audio_analyser.seg_analyser import do_analyse_segments
from voiceya.services.audio_analyser.statics import do_statics
from voiceya.services.sse import ProgressSSE

if TYPE_CHECKING:
    from io import BytesIO

    from taskiq.depends.progress_tracker import ProgressTracker

logger = logging.getLogger(__file__)


async def do_analyse(content: BytesIO, progress: ProgressTracker):
    """Async generator: yields SSE event strings with real progress, last event has type='result'."""
    sample = await prepare_audio_for_analysis(content, progress)

    # ── Engine A: 时间分段 ─────────────────────────────────
    logger.info("Engine A 分析中…")
    await progress.set_progress(str(ProgressSSE(pct=10, msg="鸭鸭正在聆听声纹…（此步骤较慢）")))

    segmentation_results = await do_segmentation(sample)

    # ── Engine B: 声学分析（仅对有声语音段）────────────
    await progress.set_progress(str(ProgressSSE(pct=50, msg="鸭鸭听完了！正在整理笔记…")))

    analyse_results = await do_analyse_segments(sample, segmentation_results, progress)

    # ── 全局汇总统计 ───────────────────────────────────────
    await progress.set_progress(str(ProgressSSE(pct=98, msg="鸭鸭快好了…")))

    result = do_statics(analyse_results)
    logger.info(
        "分析完成 — %d 段，F0=%s Hz，性别评分=%s，女性占比=%.3f",
        len(analyse_results),
        result["overall_f0"],
        result["overall_gender_score"],
        result["female_ratio"],
    )

    result["filename"] = "upload"

    return result
