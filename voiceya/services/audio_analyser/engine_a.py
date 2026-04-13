import asyncio
import logging
import time
from typing import TYPE_CHECKING

from fastapi import HTTPException

from voiceya.services.audio_analyser.seg import SEG

if TYPE_CHECKING:
    from io import BytesIO

logger = logging.getLogger(__file__)


async def do_segmentation(sample: BytesIO, results: list):
    loop = asyncio.get_running_loop()

    seg_promise = loop.run_in_executor(None, SEG, sample)
    while not seg_promise.done():
        try:
            await asyncio.wait_for(asyncio.shield(seg_promise), timeout=15)

        except asyncio.TimeoutError:
            yield {
                "type": "progress",
                "pct": 10,
                "msg": f"鸭鸭正在聆听声纹…（此步骤较慢 {time.time()}）",
            }

        except Exception as e:
            logger.error("Engine A 分析失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    results.clear()
    results.extend(seg_promise.result())
