from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Callable

import redis as sync_redis_mod
from redis.asyncio import ConnectionPool, Redis

from voiceya.config import CFG

if TYPE_CHECKING:
    from voiceya.services.sse import SSE

POOL: ConnectionPool
SYNC_POOL: sync_redis_mod.ConnectionPool

EVENT_TTL_SEC = 10 * 60
EVENT_MAXLEN = 1000


def init_redis():
    global POOL, SYNC_POOL
    POOL = ConnectionPool.from_url(url=CFG.redis_uri, decode_responses=True)
    SYNC_POOL = sync_redis_mod.ConnectionPool.from_url(url=CFG.redis_uri, decode_responses=True)


def get_redis():
    return Redis(connection_pool=POOL)


PublisherT = Callable[["SSE"], None]


def _events_key(task_id: str) -> str:
    return f"events:{task_id}"


def get_event_publister(task_id: str) -> PublisherT:
    """Return a sync publisher that XADDs SSE events to a Redis Stream.

    Streams are used (instead of pub/sub) so a late subscriber can replay
    events emitted before it connected.
    """
    r = sync_redis_mod.Redis(connection_pool=SYNC_POOL)
    key = _events_key(task_id)

    def publisher(event: "SSE"):
        payload = json.dumps(asdict(event), ensure_ascii=False)
        r.xadd(key, {"d": payload}, maxlen=EVENT_MAXLEN, approximate=True)
        r.expire(key, EVENT_TTL_SEC)

    return publisher


async def stream_events(task_id: str, block_ms: int = 15_000):
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
            for entry_id, fields in entries:
                last_id = entry_id
                yield fields["d"]


async def events_key_exists(task_id: str) -> bool:
    return bool(await get_redis().exists(_events_key(task_id)))
