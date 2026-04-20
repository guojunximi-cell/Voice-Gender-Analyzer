import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException

from voiceya.services.audio_analyser import seg as _seg

if TYPE_CHECKING:
    from io import BytesIO


logger = logging.getLogger(__name__)


async def do_segmentation(sample: "BytesIO"):
    try:
        return await asyncio.to_thread(_seg.SEG, sample)

    except Exception as e:
        logger.error("Engine A 分析失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
