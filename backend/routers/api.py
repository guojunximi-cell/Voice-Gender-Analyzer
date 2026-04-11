import asyncio
import json

import pyrate_limiter as pl
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi_limiter.depends import RateLimiter

from backend.audio_analyser import do_analyse_stream, do_analyse
from backend.config import CFG
from backend.queue import Queue
from backend.utils.is_valid_audio_file import is_valid_audio_file

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

RATE_LIMITER = pl.Limiter(
    pl.Rate(CFG.rate_limit_ct, pl.Duration.SECOND * CFG.rate_limit_duration_sec)
)


@router.post(
    "/analyze-voice",
    dependencies=[
        Depends(RateLimiter(limiter=RATE_LIMITER)),
    ],
)
async def analyze_voice(request: Request, files: list[UploadFile]):
    # ── 4. SSE 流式响应（单文件 + Accept: text/event-stream）──
    wants_stream = len(files) == 1 and "text/event-stream" in request.headers.get("accept", "")

    # ── 3. 队列控制：超出最大等待数时拒绝，否则排队 ──────────
    await Queue.enqueue()

    for f in files:
        # ── 2. 文件安全校验 ────────────────────────────────────────
        header = await f.read(12)
        filename = is_valid_audio_file(f.filename, header)
        rest = await f.read(CFG.max_file_size_mb * 1024 * 1024 - 12)
        # 文件大小限制（多读 1 字节判断是否超限，避免大文件载入内存）
        if f.read(1):
            raise FILE_EXCEED_SIZE_LIMIT_EXCEPTION

        if wants_stream:
            # Read file content eagerly here — UploadFile's SpooledTemporaryFile
            # may be closed after this function returns, before the lazy streaming
            # generator gets a chance to call file.read(), causing "read of closed file".
            async def _guarded_stream():
                """Hold semaphore & queue slot for the full streaming lifetime."""
                try:
                    async with Queue.processing_sem:
                        async for chunk in do_analyse_stream(filename, header + rest):
                            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                finally:
                    await Queue.dequeue()

            return StreamingResponse(
                _guarded_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # ── 5. 经典 JSON 响应（批量 / 不支持 SSE 的客户端）────────
        try:
            # 获取信号量 → 同时最多 MAX_CONCURRENT 个请求在处理
            async with Queue.processing_sem:
                results = await asyncio.gather(do_analyse(filename, header + rest))

        finally:
            await Queue.dequeue()

        return results if len(results) > 1 else results[0]
