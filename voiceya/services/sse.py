import asyncio
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, kw_only=True)
class SSE:
    type: Literal["wait", "progress", "error", "result"]


@dataclass(frozen=True, kw_only=True)
class WaitSSE(SSE):
    type: Literal["wait"] = "wait"
    num_to_wait: int
    msg: str


@dataclass(frozen=True, kw_only=True)
class ProgressSSE(SSE):
    type: Literal["progress"] = "progress"
    pct: int
    msg: str


@dataclass(frozen=True, kw_only=True)
class ErrorSSE(SSE):
    type: Literal["error"] = "error"
    code: int | None = None
    msg: str


@dataclass(frozen=True, kw_only=True)
class ResultSSE(SSE):
    type: Literal["result"] = "result"
    data: dict[str, Any]


class SSEStore:
    def __init__(self) -> None:
        self._q: asyncio.Queue[SSE] = asyncio.Queue()
        self.has_done: bool = False

    async def publish(self, event: SSE):
        await self._q.put(event)

    async def subscribe(self):
        if self.has_done:
            return

        while True:
            event = await self._q.get()

            yield event

            if isinstance(event, (ResultSSE, ErrorSSE)):
                self.done()
                break

    def done(self):
        self.has_done = True
