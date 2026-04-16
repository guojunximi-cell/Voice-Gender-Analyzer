import asyncio
import json
from typing import TYPE_CHECKING, Any, AsyncGenerator

from fastapi import HTTPException
from taskiq.depends.progress_tracker import TaskProgress

from voiceya.config import CFG
from voiceya.services.redis import get_redis
from voiceya.services.sse import ErrorSSE, PayloadT, PublisherT, ResultSSE
from voiceya.taskiq import TaskStage, broker

if TYPE_CHECKING:
    from voiceya.services.sse import PayloadDictT

__all__ = [
    "PayloadT",
    "PayloadDictT",
    "PublisherT",
    "events_exist_for_task",
    "get_event_publister",
    "subscribe_to_events",
    "subscribe_to_events_and_generate_sse",
]


def _events_key(task_id: str) -> str:
    return f"events:{task_id}"


async def events_exist_for_task(task_id: str) -> bool:
    return bool(await get_redis().exists(_events_key(task_id)))


def get_event_publister(task_id: str) -> PublisherT:
    """Return a sync publisher that XADDs SSE events to a Redis Stream.

    Streams are used (instead of pub/sub) so a late subscriber can replay
    events emitted before it connected.
    """

    r = get_redis()
    key = _events_key(task_id)

    async def publisher(event: PayloadT):
        await r.xadd(key, event.to_dict(), maxlen=100, approximate=True)
        await r.expire(key, CFG.task_events_ttl_sec)

    return publisher


async def subscribe_to_events(
    task_id: str, block_ms: int = 15_000
) -> "AsyncGenerator[PayloadDictT | None]":
    """Async generator yielding event JSON strings; yields ``None`` on idle tick."""

    r = get_redis()
    key = _events_key(task_id)
    last_id = "0-0"
    while True:
        resp = await r.xread({key: last_id}, block=block_ms)
        if not resp:
            yield None

            continue

        for _, entries in resp:
            for msg_id, event in entries:
                last_id = msg_id
                yield event


TICK_STEP_MS = 2_000


async def subscribe_to_events_and_generate_sse(task_id: str, progress: TaskProgress[Any]):
    while progress.state == TaskStage.PENDING:
        yield f"data: {json.dumps({'type': 'queue', 'num_to_wait': -1, 'msg': '排队等候中'})}\n\n"

        await asyncio.sleep(TICK_STEP_MS / 1000)

        progress = await broker.result_backend.get_progress(task_id)
        assert progress is not None

    # so it can also provide result in subsequent calls
    events_stream = subscribe_to_events(task_id, block_ms=TICK_STEP_MS)
    while progress.state == TaskStage.STARTED:
        event = await anext(events_stream)
        if event:
            yield f"data: {json.dumps(event)}\n\n"

        yield ": ping\n\n"

        progress = await broker.result_backend.get_progress(task_id)
        assert progress is not None

    # 任务刚结束时结果可能还没写入 backend（taskiq 的 set_result 是在 progress
    # 转为终态之后发生的）。短暂重试一下，避免 ResultIsMissingError 把连接打爆。
    import taskiq_redis.exceptions as _tq_exc

    for _ in range(10):
        try:
            result = await broker.result_backend.get_result(task_id)
            break
        except _tq_exc.ResultIsMissingError:
            await asyncio.sleep(0.2)
    else:
        result = await broker.result_backend.get_result(task_id)
    if result.is_err:
        e = result.error
        if isinstance(e, HTTPException):
            yield f"data: {json.dumps(ErrorSSE(code=e.status_code, msg=e.detail).to_dict())}\n\n"

        else:
            yield f"data: {json.dumps(ErrorSSE(msg=str(e)).to_dict())}\n\n"

        return

    yield f"data: {json.dumps(ResultSSE(data=result.return_value).to_dict())}\n\n"
