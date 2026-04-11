import asyncio
import logging
import sys

from inaSpeechSegmenter.segmenter import Segmenter

logger = logging.getLogger(__name__)

SEG: Segmenter


async def load_seg():
    global SEG
    logger.info("正在将 AI 模型载入内存...")
    try:
        loop = asyncio.get_event_loop()
        SEG = await loop.run_in_executor(None, lambda: Segmenter(detect_gender=True, ffmpeg=None))

    except Exception as e:
        logger.fatal("Engine A 加载失败: %s", e)
        sys.exit(-1)

    # ── logit 模型诊断 ──
    logger.info("Engine A (inaSpeechSegmenter) 加载完毕")
    if SEG and hasattr(SEG, "gender"):
        _g = SEG.gender
        logger.info(
            "[Gender诊断] 最后3层: %s",
            [(type(layer).__name__, getattr(layer, "name", "?")) for layer in _g.nn.layers[-3:]],
        )
        logger.info(
            "[Gender诊断] logit_model=%s  pen_model=%s  dense_W=%s",
            getattr(_g, "_logit_model", "MISSING"),
            getattr(_g, "_pen_model", "MISSING"),
            _dense_W.shape if (_dense_W := getattr(_g, "_dense_W", None)) else None,
        )

    return
