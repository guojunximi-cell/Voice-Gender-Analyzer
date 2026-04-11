import asyncio
import io
import logging
import sys
import uuid

import av

from backend.audio_analyser.auto_tools import get_duraton_sec, normalize_to_pcm
from backend.audio_analyser.engine_a import do_segmentation
from backend.audio_analyser.seg import SEG
from backend.audio_analyser.seg_analyser import do_analyse_segments
from backend.audio_analyser.statics import do_statics
from backend.config import CFG

if sys.version_info < (3, 14):
    import uuid6 as uuid

logger = logging.getLogger(__file__)


async def do_analyse_stream(filename: str, content: bytes):
    """Async generator: yields SSE event strings with real progress, last event has type='result'."""
    if SEG is None:
        raise RuntimeError("Engine A (inaSpeechSegmenter) 未能成功加载，无法分析")

    task_id = uuid.uuid7()
    logger.info("收到文件 [{}] ({:,} B)", task_id, len(content))

    source = io.BytesIO(content)
    loop = asyncio.get_running_loop()

    with av.open(source, "r") as s:
        # ── 时长限制 ───────────────────────────────────────────
        yield {"type": "progress", "pct": 8, "msg": "鸭鸭在检查音频时长…"}
        try:
            duration = await loop.run_in_executor(None, get_duraton_sec, s)

        except Exception as e:
            logger.warning("无法获取音频时长 [%s]: %s", task_id, e)

        else:
            if duration > CFG.max_audio_duration_sec:
                yield {
                    "type": "error",
                    "code": 413,
                    "msg": f"音频时长 {duration:.0f} 秒，超过 {CFG.max_audio_duration_sec} 秒）限制",
                }
                return

            logger.info("音频时长 %.1f 秒 [%s]", duration, task_id)

        # ── 转码：统一为 64kbps 单声道 MP3，降低后续 I/O 开销 ──
        yield {"type": "progress", "pct": 5, "msg": "鸭鸭正在处理音频…"}
        try:
            sample = await loop.run_in_executor(None, normalize_to_pcm, s)
            logger.info("已转码为标准化 MP3 [%s]", task_id)

        except Exception as e:
            logger.warning("ffmpeg 转码失败，回退至原始文件 [%s]: %s", task_id, e)
            sample = source

    # ── Engine A: 时间分段 ─────────────────────────────────
    logger.info("Engine A 分析中... [%s]", task_id)
    yield {"type": "progress", "pct": 10, "msg": "鸭鸭正在聆听声纹…（此步骤较慢）"}

    segmentation_results = list()
    async for event in do_segmentation(task_id, sample, segmentation_results):
        yield event

    # ── Engine B: 声学分析（仅对有声语音段）────────────
    yield {"type": "progress", "pct": 50, "msg": "鸭鸭听完了！正在整理笔记…"}

    analyse_results = list()
    async for event in do_analyse_segments(task_id, sample, segmentation_results, analyse_results):
        yield event

    # ── 全局汇总统计 ───────────────────────────────────────
    yield {"type": "progress", "pct": 98, "msg": "鸭鸭快好了…"}

    result = do_statics(segmentation_results)
    logger.info(
        "分析完成 [%s] — %d 段，F0=%s Hz，性别评分=%s，女性占比=%.3f",
        task_id,
        len(analyse_results),
        result["overall_f0"],
        result["overall_gender_score"],
        result["female_ratio"],
    )

    result["filename"] = filename

    yield {"type": "result", "pct": 100, "data": result}


async def do_analyse(filename: str, content: bytes):
    """Non-streaming wrapper: consumes the stream generator, returns the final result."""
    async for event in do_analyse_stream(filename, content):
        if event.get("type") == "result":
            return event["data"]

        if event.get("type") == "error":
            return {"status": "error", "message": event["msg"]}

    return {"status": "error", "message": "未收到分析结果"}
