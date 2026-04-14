from dataclasses import asdict, dataclass


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
