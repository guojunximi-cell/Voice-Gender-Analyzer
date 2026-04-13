from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import redis as sync_redis_mod
from redis.asyncio import ConnectionPool, Redis

from voiceya.config import CFG

if TYPE_CHECKING:
    from redis.typing import EncodableT

POOL: ConnectionPool
SYNC_POOL: sync_redis_mod.ConnectionPool


def init_redis():
    global POOL, SYNC_POOL
    POOL = ConnectionPool.from_url(url=CFG.redis_uri, decode_responses=True)
    SYNC_POOL = sync_redis_mod.ConnectionPool.from_url(url=CFG.redis_uri, decode_responses=True)


def get_redis():
    return Redis(connection_pool=POOL)


PublisherT = Callable[[Any], None]


def get_event_publister(task_id: str) -> PublisherT:
    r = sync_redis_mod.Redis(connection_pool=SYNC_POOL)
    channel = f"events:{task_id}"

    def publisher(event: EncodableT):
        r.publish(channel, event)

    return publisher


async def subscribe_to_events(task_id: str):
    redis = get_redis()
    p = redis.pubsub()
    await p.subscribe(f"events:{task_id}")

    return p
