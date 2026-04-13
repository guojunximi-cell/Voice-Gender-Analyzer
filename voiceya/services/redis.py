from typing import TYPE_CHECKING

from redis.asyncio import ConnectionPool, Redis

from voiceya.config import CFG

if TYPE_CHECKING:
    from typing import Callable

    from redis.typing import EncodableT

POOL: ConnectionPool


def init_redis():
    global POOL
    POOL = ConnectionPool.from_url(url=CFG.redis_uri, decode_responses=True)


def get_redis():
    return Redis(connection_pool=POOL)


PublisherT = Callable[[EncodableT], None]


def get_event_publister(task_id: str) -> PublisherT:
    redis = get_redis()
    channel = f"events:{task_id}"

    def publisher(event: EncodableT):
        redis.publish(channel, event)

    return publisher


async def subscribe_to_events(task_id: str):
    redis = get_redis()
    p = redis.pubsub()
    await p.subscribe(f"events:{task_id}")

    return p
