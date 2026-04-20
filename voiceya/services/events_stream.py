from abc import ABC, abstractmethod
from typing import AsyncGenerator, Awaitable, Callable

from redis.typing import EncodableT, FieldT

from voiceya.config import CFG
from voiceya.services.redis import get_redis


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
