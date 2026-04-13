import asyncio

from fastapi import HTTPException

from backend.config import CFG

QUEUE_IS_FULL_EXCEPTION = HTTPException(
    status_code=503,
    detail=f"服务器繁忙，当前排队已达上限 ({CFG.max_queue_depth})，请稍后再试",
)


class Queue:
    depth = 0
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(CFG.max_concurrent)

    @classmethod
    async def enqueue(cls):
        async with cls.lock:
            if Queue.depth > CFG.max_queue_depth:
                raise QUEUE_IS_FULL_EXCEPTION

            cls.depth += 1

        return

    @classmethod
    async def dequeue(cls):
        async with cls.lock:
            if cls.depth <= 0:
                return

            cls.depth -= 1

        return
