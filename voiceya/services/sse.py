import asyncio
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from taskiq_redis.exceptions import ResultIsMissingError

from voiceya.services.events_stream import PayloadT, subscribe_to_events
from voiceya.taskiq import TaskStage, broker

if TYPE_CHECKING:
    from typing import Any

    from taskiq.depends.progress_tracker import TaskProgress

    from voiceya.services.events_stream import PayloadDictT


@dataclass(frozen=True, kw_only=True)
class SSE(PayloadT):
    type: Literal["queue", "progress", "error", "result"]

    def to_dict(self) -> PayloadDictT:
        return asdict(self)  # type: ignore


@dataclass(frozen=True, kw_only=True)
class QueueSSE(SSE):
    type: Literal["queue"] = "queue"
    num_to_wait: int
    msg: str


@dataclass(frozen=True, kw_only=True)
class ProgressSSE(SSE):
    type: Literal["progress"] = "progress"
    pct: int
    msg: str


@dataclass(frozen=True, kw_only=True)
class ErrorSSE(SSE):
    type: Literal["error"] = "error"
    code: int | None = None
    msg: str


@dataclass(frozen=True, kw_only=True)
class ResultSSE(SSE):
    type: Literal["result"] = "result"
    data: Any


TICK_STEP_MS = 15_000


async def subscribe_to_events_and_generate_sse(task_id: str, progress: TaskProgress[Any]):
    while progress.state == TaskStage.PENDING:
        yield f"data: {json.dumps(QueueSSE(num_to_wait=-1, msg='排队等候中').to_dict())}\n\n"

        await asyncio.sleep(TICK_STEP_MS / 5 / 1000)

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

    await asyncio.sleep(1)
    for _ in range(5):
        try:
            result = await broker.result_backend.get_result(task_id)
            break

        except ResultIsMissingError:
            await asyncio.sleep(1)

    else:
        yield f"data: {json.dumps(ErrorSSE(msg='no results have been found').to_dict())}\n\n"
        return

    if result.is_err:
        e = result.error
        if isinstance(e, HTTPException):
            yield f"data: {json.dumps(ErrorSSE(code=e.status_code, msg=e.detail).to_dict())}\n\n"

        else:
            yield f"data: {json.dumps(ErrorSSE(msg=str(e)).to_dict())}\n\n"

        return

    yield f"data: {json.dumps(ResultSSE(data=result.return_value).to_dict())}\n\n"
