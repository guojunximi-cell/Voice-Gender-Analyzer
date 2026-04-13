import asyncio
import logging
from io import BytesIO
from typing import TYPE_CHECKING

import av
from av import AudioStream
from fastapi import HTTPException

from voiceya.config import CFG
from voiceya.services.sse import ProgressSSE

if TYPE_CHECKING:
    from av.container import InputContainer

    from voiceya.services.redis import PublisherT

logger = logging.getLogger(__file__)


def get_duraton_sec(s: InputContainer) -> int:
    i_stm = s.streams.best("audio")
    assert isinstance(i_stm, AudioStream)

    duration = i_stm.duration // i_stm.sample_rate  # type: ignore
    logger.info("音频时长 %i 秒", duration)

    return duration


def normalize_to_pcm(s: InputContainer) -> BytesIO:
    i_stm = s.streams.best("audio")
    assert isinstance(i_stm, AudioStream)
    i_stm.codec_context.thread_type = "AUTO"

    pcm = BytesIO()
    with av.open(pcm, "w") as t:
        o_stm = t.add_stream("pcm_s16le", rate=22050)
        assert isinstance(o_stm, AudioStream)
        o_stm.codec_context.thread_type = "AUTO"
        o_stm.codec_context.layout = "mono"
        o_stm.codec_context.bit_rate = 16_000

        for frame in s.decode(i_stm):
            for packet in o_stm.codec_context.encode_lazy(frame):
                t.mux_one(packet)

        t.mux(o_stm.encode())

    logger.info("已转码为标准化 PCM")

    return pcm


async def prepare_audio_for_analysis(source: BytesIO, publish: PublisherT):
    with av.open(source, "r") as s:
        # ── 转码：统一为 16kbps 单声道 pcm，降低后续 I/O 开销 ──
        publish(str(ProgressSSE(pct=5, msg="鸭鸭正在处理音频…")))
        try:
            sample = await asyncio.to_thread(normalize_to_pcm, s)

        except Exception as e:
            logger.error("ffmpeg 转码失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    # do gc
    source.close()
    del source

    with av.open(sample, "r") as s:
        # ── 时长限制 ───────────────────────────────────────────
        publish(str(ProgressSSE(pct=8, msg="鸭鸭在检查音频时长…")))
        duration = await asyncio.to_thread(get_duraton_sec, s)
        if duration > CFG.max_audio_duration_sec:
            raise HTTPException(
                status_code=413,
                detail=f"音频时长 {duration} 秒，超过 {CFG.max_audio_duration_sec} 秒限制",
            )

    return sample
