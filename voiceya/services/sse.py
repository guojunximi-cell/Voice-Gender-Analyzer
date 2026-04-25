from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from taskiq_redis.exceptions import ResultIsMissingError

from voiceya.services.events_stream import PayloadT, subscribe_to_events
from voiceya.services.queue_position import get_position
from voiceya.taskiq import TaskStage, broker

if TYPE_CHECKING:
    from typing import Any

    from taskiq.depends.progress_tracker import TaskProgress

    from voiceya.services.events_stream import PayloadDictT


@dataclass(frozen=True, kw_only=True)
class SSE(PayloadT):
    type: Literal["queue", "progress", "error", "result"]

    def to_dict(self) -> PayloadDictT:
        # Redis XADD can't serialize None or nested dicts, so drop Nones and
        # JSON-encode the `msg_params` dict (decoded client-side).
        d = asdict(self)  # type: ignore
        out: PayloadDictT = {}
        for k, v in d.items():
            if v is None:
                continue
            if k == "msg_params" and isinstance(v, dict):
                out[k] = json.dumps(v)
            else:
                out[k] = v
        return out


@dataclass(frozen=True, kw_only=True)
class QueueSSE(SSE):
    type: Literal["queue"] = "queue"
    num_to_wait: int
    msg: str
    msg_key: str | None = None


@dataclass(frozen=True, kw_only=True)
class ProgressSSE(SSE):
    type: Literal["progress"] = "progress"
    pct: int
    msg: str
    # Optional i18n key + params so the frontend can render the progress label
    # in the current UI language instead of showing the Chinese fallback.
    msg_key: str | None = None
    msg_params: dict[str, Any] | None = None


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
# STARTED 阶段：worker 发完最后一个 progress 事件（如 pct=98）就 return，之后不再
# 产生新事件。XREAD 的 block 间隔决定了 SSE 转发感知 progress=SUCCESS 的最大延迟。
# 设 500 ms 让"鸭鸭快好了"到 result 之间的尾延迟从 ~15s 压到 <0.5s；每秒 2 次
# Redis XREAD + 2 次 SSE keep-alive，对单连接成本可忽略。
EVENT_BLOCK_MS = 500


async def subscribe_to_events_and_generate_sse(task_id: str, progress: TaskProgress[Any]):
    while progress.state == TaskStage.PENDING:
        pos = await get_position(task_id)
        yield f"data: {json.dumps(QueueSSE(num_to_wait=pos, msg='排队等候中', msg_key='progress.queued').to_dict())}\n\n"

        await asyncio.sleep(TICK_STEP_MS / 5 / 1000)

        progress = await broker.result_backend.get_progress(task_id)
        assert progress is not None

    # so it can also provide result in subsequent calls
    events_stream = subscribe_to_events(task_id, block_ms=EVENT_BLOCK_MS)
    while progress.state == TaskStage.STARTED:
        event = await anext(events_stream)
        if event:
            yield f"data: {json.dumps(event)}\n\n"

        yield ": ping\n\n"

        progress = await broker.result_backend.get_progress(task_id)
        assert progress is not None

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
