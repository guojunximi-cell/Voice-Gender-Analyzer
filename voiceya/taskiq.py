from contextlib import AsyncExitStack

from taskiq import TaskiqEvents, TaskiqState
from taskiq.abc.formatter import TaskiqFormatter
from taskiq.message import BrokerMessage, TaskiqMessage
from taskiq.serializers import MSGPackSerializer
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from voiceya.config import CFG


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
    result_ex_time=5 * 60,
    serializer=MSGPackSerializer(),
)

broker = (
    RedisStreamBroker(
        url=CFG.redis_uri,
        maxlen=CFG.max_queue_depth * 3,
    )
    .with_serializer(MSGPackSerializer())
    .with_result_backend(result_backend)
)
broker.formatter = PythonModeFormatter(broker)


# Run the FastAPI lifespan inside the worker process so init_redis() / load_seg()
# fire there too. We avoid taskiq_fastapi.init because taskiq-fastapi 0.4.0 still
# calls Router.startup(), which starlette>=1.0 removed.
_lifespan_stack: AsyncExitStack | None = None


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _worker_startup(_state: TaskiqState) -> None:
    from voiceya.main import app

    global _lifespan_stack
    _lifespan_stack = AsyncExitStack()
    await _lifespan_stack.enter_async_context(app.router.lifespan_context(app))


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _worker_shutdown(_state: TaskiqState) -> None:
    global _lifespan_stack
    if _lifespan_stack is not None:
        await _lifespan_stack.aclose()
        _lifespan_stack = None
