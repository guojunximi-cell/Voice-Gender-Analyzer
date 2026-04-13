import io
import json
import logging

from fastapi import HTTPException
from taskiq import TaskiqDepends
from taskiq.depends.progress_tracker import Context

from voiceya.services.audio_analyser import do_analyse
from voiceya.services.redis import events_key_exists, get_event_publister, stream_events
from voiceya.services.sse import ErrorSSE, ResultSSE
from voiceya.taskiq import broker

# Idle ticks (each = block_ms in stream_events) before giving up on an unknown task.
_UNKNOWN_TASK_GRACE_TICKS = 2


@broker.task(timeout=15 * 60)
async def analyse_voice(
    content: bytes,
    context: Context = TaskiqDepends(),
):
    logging.getLogger(__name__).info(
        "worker 收到 %d 字节，头 16: %r", len(content), content[:16]
    )
    buf = io.BytesIO(content)
    publish = get_event_publister(context.message.task_id)

    try:
        result = await do_analyse(buf, publish)
        publish(ResultSSE(data=result))
        return result

    except HTTPException as e:
        publish(ErrorSSE(code=e.status_code, msg=e.detail))
        raise

    except Exception as e:
        publish(ErrorSSE(msg=str(e)))
        raise


async def subscribe_to_task_and_generate_sse(task_id: str):
    idle_ticks = 0
    async for event in stream_events(task_id, block_ms=15_000):
        if event is None:
            yield ": ping\n\n"
            idle_ticks += 1
            # Bail on unknown task ids: if the stream key never appeared and
            # no result is registered, the id is bogus or the worker is gone.
            if idle_ticks >= _UNKNOWN_TASK_GRACE_TICKS and not await events_key_exists(task_id):
                if not await broker.result_backend.is_result_ready(task_id):
                    payload = json.dumps(
                        {"type": "error", "code": 404, "msg": f"task '{task_id}' not found"}
                    )
                    yield f"data: {payload}\n\n"
                    return
            continue

        idle_ticks = 0
        yield f"data: {event}\n\n"

        # Terminal events end the stream. Cheap substring check avoids re-parsing.
        if '"type": "result"' in event or '"type": "error"' in event:
            return
