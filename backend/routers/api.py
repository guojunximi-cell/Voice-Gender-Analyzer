import asyncio
import io
import logging

import pyrate_limiter as pl
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi_limiter.depends import RateLimiter

from voiceya.config import CFG
from voiceya.queue import Queue
from voiceya.services.analyser_sse_stream import analyse_and_warp_to_sse
from voiceya.services.audio_analyser import do_analyse_legacy
from voiceya.utils.is_valid_audio_file import is_valid_audio_file

logger = logging.getLogger(__file__)

router = APIRouter(tags=["api"])


API_CONFIGS = {
    "max_concurrent": CFG.max_concurrent,
    "max_queue_depth": CFG.max_queue_depth,
    "allow_concurrent": CFG.max_concurrent > 1,
    "max_file_size_mb": CFG.max_file_size_mb,
    "max_audio_duration_sec": CFG.max_audio_duration_sec,
}


@router.get("/config")
def get_config():
    """配置接口"""

    return API_CONFIGS


FILE_EXCEED_SIZE_LIMIT_EXCEPTION = HTTPException(
    status_code=413,
    detail=f"上传的音频文件超过 {CFG.max_file_size_mb} MB 大小限制",
)

__RATE_LIMITER = pl.Limiter(
    pl.Rate(CFG.rate_limit_ct, pl.Duration.SECOND * CFG.rate_limit_duration_sec)
)


@router.post(
    "/analyze-voice",
    dependencies=[
        Depends(RateLimiter(limiter=__RATE_LIMITER)),
    ],
)
async def analyze_voice(request: Request):
    # ── 3. 队列控制：超出最大等待数时拒绝，否则排队 ──────────
    await Queue.enqueue()

    # ── 2. 加载文件 ──────────────────────────────────────
    file_stream = request.stream()
    buf = io.BytesIO()
    # read the minimum amount of bytes that is required to check validity
    while (pos := buf.tell()) < 12:
        buf.write(await anext(file_stream))

    # check if file is valid
    buf.seek(0)
    is_valid_audio_file(buf.read(12))
    buf.seek(pos)

    async for chunk in file_stream:
        buf.write(chunk)

        if buf.tell() > CFG.max_file_size_mb * 1024 * 1024:
            raise FILE_EXCEED_SIZE_LIMIT_EXCEPTION

    logger.info("收到文件 ({:,} B)", buf.tell())
    buf.seek(0)

    # ── 4. SSE 流式响应（单文件 + Accept: text/event-stream）──
    if "text/event-stream" in request.headers.get("accept", ""):
        try:
            return StreamingResponse(
                analyse_and_warp_to_sse(buf),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        finally:
            await Queue.dequeue()

    # ── 5. 经典 JSON 响应（批量 / 不支持 SSE 的客户端）────────
    try:
        # 获取信号量 → 同时最多 MAX_CONCURRENT 个请求在处理
        async with Queue.sem:
            results = await asyncio.gather(do_analyse_legacy(buf))

        return results if len(results) > 1 else results[0]

    finally:
        await Queue.dequeue()
