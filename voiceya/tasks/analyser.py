import io
import logging
from typing import Annotated, Literal

from taskiq import TaskiqDepends
from taskiq.depends.progress_tracker import Context, ProgressTracker

from voiceya.config import CFG
from voiceya.services.audio_analyser import do_analyse
from voiceya.services.events_stream import (
    get_event_publister,
)
from voiceya.taskiq import TaskStage, broker

logger = logging.getLogger(__name__)


@broker.task(timeout=CFG.task_max_exec_sec)
async def analyse_voice(
    content: bytes,
    context: Annotated[Context, TaskiqDepends()],
    progress_tacker: Annotated[ProgressTracker, TaskiqDepends()],
    mode: Literal["free", "script"] = "free",
    script: str | None = None,
    language: Literal["zh-CN", "en-US"] = "zh-CN",
):
    await progress_tacker.set_progress(TaskStage.STARTED)
    logger.info(
        "worker 收到 %d 字节，mode=%s，language=%s，头 16: %r",
        len(content),
        mode,
        language,
        content[:16],
    )

    buf = io.BytesIO(content)
    publish = get_event_publister(context.message.task_id)
    try:
        result = await do_analyse(buf, publish, mode=mode, script=script, language=language)

    except Exception:
        await progress_tacker.set_progress(TaskStage.FAILURE)
        raise

    await progress_tacker.set_progress(TaskStage.SUCCESS)
    return result
