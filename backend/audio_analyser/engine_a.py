import asyncio
import logging
import time
from typing import TYPE_CHECKING

from backend.audio_analyser.seg import SEG

if TYPE_CHECKING:
    from io import BytesIO
    from uuid import UUID

logger = logging.getLogger(__file__)


async def do_segmentation(task_id: UUID, sample: BytesIO, results: list):
    loop = asyncio.get_running_loop()

    _seg_promise = loop.run_in_executor(None, SEG, sample)
    while not _seg_promise.done():
        # 用 keepalive ping 防止 Railway 代理因长时间无数据而关闭 SSE 连接
        try:
            await asyncio.wait_for(asyncio.shield(_seg_promise), timeout=15)

        except asyncio.TimeoutError:
            yield {
                "type": "progress",
                "pct": 10,
                "msg": f"鸭鸭正在聆听声纹…（此步骤较慢 {time.time()}）",
            }

        except Exception as e:
            logger.error("分析失败 [Task: %s]: %s", task_id, e)
            yield {"type": "error", "msg": str(e)}
            return

    results.clear()
    results.extend(await _seg_promise)
