import asyncio
import io

from fastapi import HTTPException
from taskiq import TaskiqDepends
from taskiq.depends.progress_tracker import Context

from voiceya.services.audio_analyser import do_analyse
from voiceya.services.redis import get_event_publister, subscribe_to_events
from voiceya.services.sse import ErrorSSE, ResultSSE
from voiceya.taskiq import broker


@broker.task(timeout=15 * 60)
async def analyse_voice(
    content: bytes,
    context: Context = TaskiqDepends(),
):
    buf = io.BytesIO(content)
    publish = get_event_publister(context.message.task_id)

    try:
        return await do_analyse(buf, publish)

    except HTTPException as e:
        publish(str(ErrorSSE(code=e.status_code, msg=str(e))))
        raise e

    except Exception as e:
        publish(str(ErrorSSE(msg=str(e))))
        raise e


async def subscribe_to_task_and_generate_sse(task_id: str):
    subscriber = await subscribe_to_events(task_id)

    while not await broker.result_backend.is_result_ready(task_id):
        promise = asyncio.create_task(subscriber.get_message())
        guard = 0
        while not promise.done():
            try:
                await asyncio.wait_for(asyncio.shield(promise), timeout=15)

            except asyncio.TimeoutError:
                yield ": ping"

            if guard > 200:
                promise.cancel()
                break

            guard += 1

        else:
            yield f"data: {await promise}"

    yield f"data: {ResultSSE(data=await broker.result_backend.get_result(task_id))}"
