import asyncio
import io
import logging
from typing import Literal

import av
import pyrate_limiter as pl
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi_limiter.depends import RateLimiter

from voiceya.config import CFG
from voiceya.services.audio_analyser.audio_tools import get_duraton_sec
from voiceya.services.sse import subscribe_to_events_and_generate_sse
from voiceya.taskiq import broker
from voiceya.tasks.analyser import analyse_voice
from voiceya.utils.is_valid_audio_file import is_valid_audio_file

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api"])


API_CONFIGS = {
    "max_concurrent": CFG.max_concurrent,
    "max_queue_depth": CFG.max_queue_depth,
    "allow_concurrent": CFG.max_concurrent > 1,
    "max_file_size_mb": CFG.max_file_size_mb,
    "max_audio_duration_sec": CFG.max_audio_duration_sec,
    "engine_c_enabled": CFG.engine_c_enabled,
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


Mode = Literal["free", "script"]


@router.post(
    "/analyze-voice",
    dependencies=[
        Depends(RateLimiter(limiter=__RATE_LIMITER)),
    ],
)
async def new_analyse(
    audio: UploadFile,
    mode: Mode = Form("free"),
    script: str | None = Form(None),
):
    # ── 3. 队列控制：超出最大等待数时拒绝，否则排队 ───────────
    # TODO: await NotifyingQueue.enqueue()

    # ── 2. 加载文件（分块读，边读边检大小上限） ───────────
    buf = io.BytesIO()
    max_bytes = CFG.max_file_size_mb * 1024 * 1024
    while chunk := await audio.read(64 * 1024):
        buf.write(chunk)
        if buf.tell() > max_bytes:
            raise FILE_EXCEED_SIZE_LIMIT_EXCEPTION

    if buf.tell() < 12:
        raise HTTPException(status_code=400, detail="上传的音频文件过小或为空")

    buf.seek(0)
    is_valid_audio_file(buf.read(12))

    logger.info("收到文件 (%d B, mode=%s)", buf.tell(), mode)
    buf.seek(0)

    # ── 时长限制 ───────────────────────────────────────────
    with av.open(buf, "r") as s:
        duration = await asyncio.to_thread(get_duraton_sec, s)
        if duration > CFG.max_audio_duration_sec:
            raise HTTPException(
                status_code=413,
                detail=f"音频时长 {duration} 秒，超过 {CFG.max_audio_duration_sec} 秒限制",
            )

    buf.seek(0)

    # ── script 模式参数校验 ───────────────────────────────
    # Engine C 关闭时 script 字段被忽略（engine_c.py 自会跳过）；这里不报错，
    # 保持 "Engine C 是可选模块" 的契约——前端应已隐藏切换。
    if mode == "script":
        script_clean = (script or "").strip()
        if not script_clean:
            raise HTTPException(
                status_code=400,
                detail="跟读模式需要提供 script 文本",
            )
    else:
        script_clean = None

    # ── kick task ─────────────────────────────────────────
    task = await analyse_voice.kiq(  # pyright: ignore[reportCallIssue]
        content=buf.read(),
        mode=mode,
        script=script_clean,
    )

    # POST→303→GET 这条链在 fetch / vite 代理 / curl 下各有坑（body 处理、Accept 是否传递、SSE
    # 连接语义），把两步拆开最稳。
    return {"task_id": task.task_id}


NOT_ACCEPTING_SSE_EXCEPTION = HTTPException(
    status_code=406, detail="this endpoint can only work with sse"
)


@router.get("/status/{task_id}")
async def get_status(request: Request, task_id: str):
    # ── 4. SSE 流式响应（单文件 + Accept: text/event-stream）──
    if "text/event-stream" not in request.headers.get("accept", ""):
        raise NOT_ACCEPTING_SSE_EXCEPTION

    progress = await broker.result_backend.get_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' cannot be found")

    return StreamingResponse(
        subscribe_to_events_and_generate_sse(task_id, progress),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
