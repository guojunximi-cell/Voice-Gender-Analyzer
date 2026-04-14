import asyncio
import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from fastapi import HTTPException

from voiceya.config import CFG
from voiceya.services.redis import get_redis
from voiceya.services.sse import ErrorSSE, ResultSSE
from voiceya.taskiq import TaskStage, broker

if TYPE_CHECKING:
    from typing import Any, AsyncGenerator, Awaitable, Callable

    from redis.typing import EncodableT, FieldT
    from taskiq.depends.progress_tracker import TaskProgress


class PayloadT(ABC):
    @abstractmethod
    def to_dict(self) -> dict[FieldT, EncodableT]: ...


PayloadDictT = dict[FieldT, EncodableT]
PublisherT = Callable[[PayloadT], Awaitable[None]]


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
) -> AsyncGenerator[PayloadDictT | None]:
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


TICK_STEP_MS = 15_000


async def subscribe_to_events_and_generate_sse(task_id: str, progress: TaskProgress[Any]):
    while progress.state is TaskStage.PENDING:
        yield f"data: {json.dumps({'type': 'queue', 'num_to_wait': -1, 'msg': '排队等候中'})}\n\n"

        await asyncio.sleep(TICK_STEP_MS)

        progress = await broker.result_backend.get_progress(task_id)
        assert progress is not None

    # so it can also provide result in subsequent calls
    events_stream = subscribe_to_events(task_id, block_ms=TICK_STEP_MS)
    while progress.state is TaskStage.STARTED:
        event = await anext(events_stream)
        if event:
            yield f"data: {event}\n\n"

        yield ": ping\n\n"

        progress = await broker.result_backend.get_progress(task_id)
        assert progress is not None

    result = await broker.result_backend.get_result(task_id)
    if result.is_err:
        e = result.error
        if isinstance(e, HTTPException):
            yield f"data: {json.dumps(ErrorSSE(code=e.status_code, msg=e.detail).to_dict())}"

        else:
            yield f"data: {json.dumps(ErrorSSE(msg=str(e)).to_dict())}"

        return

    yield f"data: {json.dumps(ResultSSE(data=result).to_dict())}"
