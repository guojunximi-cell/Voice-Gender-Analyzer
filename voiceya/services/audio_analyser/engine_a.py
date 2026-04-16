import asyncio
import logging
from io import BytesIO

from fastapi import HTTPException

from voiceya.services.audio_analyser import seg as _seg

logger = logging.getLogger(__name__)


async def do_segmentation(sample: BytesIO):
    try:
        return await asyncio.to_thread(_seg.SEG, sample)

    except Exception as e:
        logger.error("Engine A 分析失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
