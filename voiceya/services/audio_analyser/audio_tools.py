from __future__ import annotations

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

    from voiceya.services.events_stream import PublisherT

logger = logging.getLogger(__file__)


def get_duraton_sec(s: InputContainer) -> float:
    i_stm = s.streams.best("audio")
    assert isinstance(i_stm, AudioStream)

    duration = i_stm.duration * i_stm.time_base  # type: ignore
    logger.info("音频时长 %i 秒", duration)

    return float(duration)


def normalize_to_pcm(s: InputContainer) -> BytesIO:
    i_stm = s.streams.best("audio")
    assert isinstance(i_stm, AudioStream)
    i_stm.codec_context.thread_type = "AUTO"

    pcm = BytesIO()
    # 下游 Engine A（inaSpeechSegmenter, ffmpeg=None 分支）硬性要求 16 kHz 单声道 wav，
    # 所以这里直接产出 16 kHz/mono/pcm_s16le；Engine B 的 librosa 以 sr=None 加载，
    # 会沿用同一采样率，无需二次重采样。
    # NOTE: PCM 是无损原始样本流，不存在有意义的 `bit_rate`，之前那行 16_000 是把
    # 比特率当采样率用的历史遗留，删掉以免误导。
    with av.open(pcm, "w", format="wav") as t:
        o_stm = t.add_stream("pcm_s16le", rate=16000)
        assert isinstance(o_stm, AudioStream)
        o_stm.codec_context.thread_type = "AUTO"
        o_stm.codec_context.layout = "mono"

        for frame in s.decode(i_stm):
            for packet in o_stm.codec_context.encode_lazy(frame):
                t.mux_one(packet)

        t.mux(o_stm.encode())

    logger.info("已转码为标准化 PCM")

    pcm.seek(0)

    return pcm


async def normalize_audio_for_analysis(source: BytesIO, publish: PublisherT):
    with av.open(source, "r") as s:
        # ── 转码：统一为 16kbps 单声道 pcm，降低后续 I/O 开销 ──
        publish(ProgressSSE(pct=5, msg="鸭鸭正在处理音频…"))
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
        publish(ProgressSSE(pct=8, msg="鸭鸭在检查音频时长…"))
        duration = await asyncio.to_thread(get_duraton_sec, s)
        if duration > CFG.max_audio_duration_sec:
            raise HTTPException(
                status_code=413,
                detail=f"音频时长 {duration} 秒，超过 {CFG.max_audio_duration_sec} 秒限制",
            )

    sample.seek(0)

    return sample
