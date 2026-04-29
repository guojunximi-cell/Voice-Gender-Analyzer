import io
import json
import logging
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from taskiq import TaskiqDepends
from taskiq.depends.progress_tracker import Context, ProgressTracker

from voiceya.config import CFG
from voiceya.services.audio_analyser import do_analyse
from voiceya.services.events_stream import (
    get_event_publister,
)
from voiceya.services.queue_position import dequeue
from voiceya.services.sse import ErrorSSE
from voiceya.taskiq import TaskStage, broker

logger = logging.getLogger(__name__)


def _gate_violation_params(violation: dict[str, Any]) -> dict[str, Any] | None:
    """把 audio_gate 输出的 metric/value 翻译成 i18n 模板用的占位值。"""
    metric = violation.get("metric")
    value = violation.get("value")
    if value is None:
        return None
    if metric in ("clipping_ratio", "voiced_ratio"):
        return {"pct": round(float(value) * 100, 1)}
    if metric == "rms_dbfs":
        return {"db": round(float(value), 1)}
    return None


def _i18n_from_http_exception(exc: HTTPException) -> tuple[str, str | None, dict[str, Any] | None]:
    """从 HTTPException 拆出 (msg, msg_key, msg_params)。

    audio_gate 的 detail 是 JSON——把第一条违规拎出来，前端按 i18n_key 渲染。
    其他路径走 plain detail。
    """
    detail = exc.detail
    if isinstance(detail, str):
        try:
            payload = json.loads(detail)
        except (ValueError, TypeError):
            return detail, None, None
        if isinstance(payload, dict) and payload.get("error_code") == "audio_quality_rejected":
            violations = payload.get("violations") or []
            first = violations[0] if violations and isinstance(violations[0], dict) else None
            msg_key = first.get("i18n_key") if first else None
            msg_params = _gate_violation_params(first) if first else None
            return payload.get("message") or detail, msg_key, msg_params
        return detail, None, None
    return str(detail), None, None


@broker.task(timeout=CFG.task_max_exec_sec)
async def analyse_voice(
    content: bytes,
    context: Annotated[Context, TaskiqDepends()],
    progress_tacker: Annotated[ProgressTracker, TaskiqDepends()],
    mode: Literal["free", "script"] = "free",
    script: str | None = None,
    language: Literal["zh-CN", "en-US", "fr-FR"] = "zh-CN",
):
    await progress_tacker.set_progress(TaskStage.STARTED)
    await dequeue(context.message.task_id)
    logger.info(
        "worker 收到 %d 字节，mode=%s，language=%s，头 16: %r",
        len(content),
        mode,
        language,
        content[:16],
    )

    buf = io.BytesIO(content)
    publish = get_event_publister(context.message.task_id)
    # 直接把 ErrorSSE 推到 events 流，绕开 taskiq 的异常 round-trip——
    # HTTPException.args 是空的，json 序列化后再反序列化只剩 `<class …>(())`，
    # 不再依赖 result.error 重建用户可读的错误。
    try:
        result = await do_analyse(buf, publish, mode=mode, script=script, language=language)

    except HTTPException as e:
        msg, msg_key, msg_params = _i18n_from_http_exception(e)
        await publish(ErrorSSE(code=e.status_code, msg=msg, msg_key=msg_key, msg_params=msg_params))
        await progress_tacker.set_progress(TaskStage.FAILURE)
        raise

    except Exception as e:
        logger.exception("分析任务异常")
        await publish(ErrorSSE(msg=str(e) or type(e).__name__))
        await progress_tacker.set_progress(TaskStage.FAILURE)
        raise

    await progress_tacker.set_progress(TaskStage.SUCCESS)
    return result
