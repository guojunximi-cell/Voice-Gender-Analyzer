import logging
from typing import TYPE_CHECKING

from backend.services.audio_analyser.auto_tools import prepare_audio_for_analysis
from backend.services.audio_analyser.engine_a import do_segmentation
from backend.services.audio_analyser.seg_analyser import do_analyse_segments
from backend.services.audio_analyser.statics import do_statics

if TYPE_CHECKING:
    from io import BytesIO

logger = logging.getLogger(__file__)


async def do_analyse(sample: BytesIO):
    """Async generator: yields SSE event strings with real progress, last event has type='result'."""
    async for event in prepare_audio_for_analysis(sample):
        if not isinstance(event, dict):
            sample = event
            break

        yield event

    # ── Engine A: 时间分段 ─────────────────────────────────
    logger.info("Engine A 分析中…")
    yield {"type": "progress", "pct": 10, "msg": "鸭鸭正在聆听声纹…（此步骤较慢）"}

    segmentation_results = list()
    async for event in do_segmentation(sample, segmentation_results):
        yield event

    # ── Engine B: 声学分析（仅对有声语音段）────────────
    yield {"type": "progress", "pct": 50, "msg": "鸭鸭听完了！正在整理笔记…"}

    analyse_results = list()
    async for event in do_analyse_segments(sample, segmentation_results, analyse_results):
        yield event

    # ── 全局汇总统计 ───────────────────────────────────────
    yield {"type": "progress", "pct": 98, "msg": "鸭鸭快好了…"}

    result = do_statics(segmentation_results)
    logger.info(
        "分析完成 — %d 段，F0=%s Hz，性别评分=%s，女性占比=%.3f",
        len(analyse_results),
        result["overall_f0"],
        result["overall_gender_score"],
        result["female_ratio"],
    )

    result["filename"] = "upload"

    yield {"type": "result", "pct": 100, "data": result}


async def do_analyse_legacy(sample: BytesIO):
    """Non-streaming wrapper: consumes the stream generator, returns the final result."""
    async for event in do_analyse(sample):
        if event.get("type") == "result":
            return event["data"]

        if event.get("type") == "error":
            return {"status": "error", "message": event["msg"]}

    return {"status": "error", "message": "未收到分析结果"}
