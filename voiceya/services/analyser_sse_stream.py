import asyncio
import io
import json

from fastapi import HTTPException

from voiceya.config import CFG
from voiceya.queue import Queue
from voiceya.services.audio_analyser import do_analyse


async def __run_analyser_inner(buf: io.BytesIO):
    async for event in do_analyse(buf):
        yield event


async def __run_analyser(buf: io.BytesIO):
    async with Queue.sem:
        return __run_analyser_inner(buf)


async def analyse_and_warp_to_sse(buf: io.BytesIO):
    analyse_promise = asyncio.create_task(__run_analyser(buf))
    while not analyse_promise.done():
        try:
            await asyncio.wait_for(asyncio.shield(analyse_promise), timeout=15)

        except asyncio.TimeoutError:
            yield (
                "data: {"
                '"type":"wait",'
                f'"num_to_wait":{Queue.depth - CFG.max_concurrent - 1},'
                '"msg":"排队等待中…"'
                "}"
            )

    try:
        async for event in analyse_promise.result():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    except HTTPException as e:
        yield f'data: {{"type":"error","code":{e.status_code},"msg":{str(e)}}}\n\n'

    except Exception as e:
        yield f'data: {{"type":"error","msg":{str(e)}}}\n\n'
