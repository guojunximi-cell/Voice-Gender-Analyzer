from __future__ import annotations

import enum
import time
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from taskiq import TaskiqEvents, TaskiqMiddleware
from taskiq.abc.formatter import TaskiqFormatter
from taskiq.depends.progress_tracker import TaskProgress
from taskiq.message import BrokerMessage, TaskiqMessage
from taskiq.serializers import PickleSerializer
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from voiceya.config import CFG

if TYPE_CHECKING:
    from taskiq import TaskiqState


class TaskStage(enum.StrEnum):
    """State of task execution."""

    PENDING = "PENDING"
    STARTED = "STARTED"
    FAILURE = "FAILURE"
    SUCCESS = "SUCCESS"


class ProgressMiddleware(TaskiqMiddleware):
    async def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        from voiceya.services.queue_position import enqueue

        progress = TaskProgress(
            state=TaskStage.PENDING,
            meta=None,
        )

        await self.broker.result_backend.set_progress(message.task_id, progress)
        await enqueue(message.task_id, time.time())

        return message


class PythonModeFormatter(TaskiqFormatter):
    """Like taskiq's ProxyFormatter, but dumps pydantic in python mode so
    raw `bytes` arguments survive (msgpack encodes them natively)."""

    def __init__(self, broker):
        self.broker = broker

    def dumps(self, message: TaskiqMessage) -> BrokerMessage:
        return BrokerMessage(
            task_id=message.task_id,
            task_name=message.task_name,
            message=self.broker.serializer.dumpb(message.model_dump(mode="python")),
            labels=message.labels,
        )

    def loads(self, message: bytes) -> TaskiqMessage:
        return TaskiqMessage.model_validate(self.broker.serializer.loadb(message))


result_backend = RedisAsyncResultBackend(
    redis_url=CFG.redis_uri,
    result_ex_time=CFG.task_result_ttl_sec,
    serializer=PickleSerializer(),
)


broker = (
    RedisStreamBroker(
        url=CFG.redis_uri,
        maxlen=CFG.max_queue_depth + CFG.max_concurrent,
    )
    .with_serializer(PickleSerializer())
    .with_result_backend(result_backend)
    .with_middlewares(ProgressMiddleware())
)

broker.formatter = PythonModeFormatter(broker)


# Run the FastAPI lifespan inside the worker process so init_redis() / load_seg()
# fire there too. We avoid taskiq_fastapi.init because taskiq-fastapi 0.4.0 still
# calls Router.startup(), which starlette>=1.0 removed.
_LIFESPAN_STACK: AsyncExitStack | None = None


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _worker_startup(_state: TaskiqState) -> None:
    global _LIFESPAN_STACK

    if _LIFESPAN_STACK:
        return

    from voiceya.main import app

    _LIFESPAN_STACK = AsyncExitStack()

    await _LIFESPAN_STACK.enter_async_context(app.router.lifespan_context(app))


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _worker_shutdown(_state: TaskiqState) -> None:
    global _LIFESPAN_STACK

    if not _LIFESPAN_STACK:
        return

    await _LIFESPAN_STACK.aclose()

    _LIFESPAN_STACK = None
