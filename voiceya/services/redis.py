from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis

from voiceya.config import CFG

POOL: ConnectionPool


def init_redis():
    global POOL

    POOL = ConnectionPool.from_url(url=CFG.redis_uri, decode_responses=True)


def get_redis():
    return Redis(connection_pool=POOL)
