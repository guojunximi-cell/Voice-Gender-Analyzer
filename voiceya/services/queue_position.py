from __future__ import annotations

from voiceya.services.redis import get_redis

_ZSET_KEY = "voiceya:queue"


async def enqueue(task_id: str, score: float) -> None:
    await get_redis().zadd(_ZSET_KEY, {task_id: score})


async def dequeue(task_id: str) -> None:
    await get_redis().zrem(_ZSET_KEY, task_id)


async def get_position(task_id: str) -> int:
    """0-based rank (0 = next in line, nobody ahead). -1 = not in queue."""
    rank = await get_redis().zrank(_ZSET_KEY, task_id)
    return rank if rank is not None else -1
