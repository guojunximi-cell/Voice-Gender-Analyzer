import asyncio
import io

from fastapi import HTTPException
from taskiq import TaskiqDepends
from taskiq.depends.progress_tracker import ProgressTracker

from voiceya.services.audio_analyser import do_analyse
from voiceya.services.sse import ErrorSSE, ResultSSE
from voiceya.taskiq import broker


@broker.task(timeout=15 * 60)
async def analyse_voice(
    content: bytes,
    progress: ProgressTracker = TaskiqDepends(),
):
    try:
        buf = io.BytesIO(content)
        await do_analyse(buf, progress)

    except HTTPException as e:
        await progress.set_progress(str(ErrorSSE(code=e.status_code, msg=str(e))))
        raise e

    except Exception as e:
        await progress.set_progress(str(ErrorSSE(msg=str(e))))
        raise e


async def subscribe_to_task_and_generate_sse(task_id: str):
    while not await broker.result_backend.is_result_ready(task_id):
        promise = asyncio.create_task(broker.result_backend.get_progress(task_id))
        while not promise.done():
            try:
                await asyncio.wait_for(asyncio.shield(promise), timeout=15)

            except asyncio.TimeoutError:
                yield ": ping"

        yield f"data: {await promise}"

    yield f"data: {ResultSSE(data=await broker.result_backend.get_result(task_id))}"
