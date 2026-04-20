from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

from voiceya.services.events_stream import PayloadT

if TYPE_CHECKING:
    from voiceya.services.events_stream import PayloadDictT


@dataclass(frozen=True, kw_only=True)
class SSE(PayloadT):
    type: Literal["wait", "progress", "error", "result"]

    def to_dict(self) -> PayloadDictT:
        return asdict(self)  # type: ignore


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
