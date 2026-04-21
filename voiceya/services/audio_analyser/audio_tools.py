from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import TYPE_CHECKING

import av
from av import AudioStream
from fastapi import HTTPException

from voiceya.services.sse import ProgressSSE

if TYPE_CHECKING:
    from av.container import InputContainer

    from voiceya.services.events_stream import PublisherT

logger = logging.getLogger(__name__)


def get_duraton_sec(s: InputContainer) -> float:
    i_stm = s.streams.best("audio")
    assert isinstance(i_stm, AudioStream)

    # 某些容器（webm/mka 等）流级 duration 为 None，退回容器级 duration
    # （单位为 AV_TIME_BASE = 1e6 微秒）。
    if i_stm.duration is not None:
        duration = float(i_stm.duration * i_stm.time_base)  # type: ignore
        logger.info("音频时长 %.2f 秒", duration)
        return duration
    if s.duration is not None:
        duration = s.duration / 1_000_000
        logger.info("音频时长 %.2f 秒", duration)
        return duration

    # 浏览器 MediaRecorder 产出的 webm/ogg 两级 duration 都缺失 —
    # 只能实打实扫一遍流。先尝试 demux 累加包时长（不用解码，最便宜），
    # 失败再退到 decode 数采样。文件大小已被 max_file_size_mb 封顶。
    tb = i_stm.time_base
    if tb is not None:
        try:
            ticks = 0
            n_pkts = 0
            for pkt in s.demux(i_stm):
                if pkt.duration is not None:
                    ticks += pkt.duration
                    n_pkts += 1
            if n_pkts > 0 and ticks > 0:
                duration = float(ticks * tb)
                logger.info("duration 回退到包时长累加：%d 包 / %.2f 秒", n_pkts, duration)
                return duration
        except av.FFmpegError as e:
            logger.warning("demux 累加包时长失败，回退到 decode 数采样: %s", e)

    # 上面的 demux 已经把读指针推到末尾，需要重新 seek 到起点才能 decode。
    s.seek(0)
    sample_rate = i_stm.rate
    if sample_rate is None or sample_rate <= 0:
        raise HTTPException(status_code=400, detail="无法读取音频时长")
    try:
        n_samples = sum(frame.samples for frame in s.decode(i_stm))
    except av.FFmpegError as e:
        logger.error("fallback decode 读取音频时长失败: %s", e)
        raise HTTPException(status_code=400, detail="无法读取音频时长") from e
    if n_samples <= 0:
        raise HTTPException(status_code=400, detail="无法读取音频时长")
    duration = n_samples / sample_rate
    logger.info("duration 回退到样本计数：%d 采样 / %.2f 秒", n_samples, duration)
    return duration


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
        await publish(ProgressSSE(pct=5, msg="鸭鸭正在处理音频…"))
        try:
            sample = await asyncio.to_thread(normalize_to_pcm, s)

        except Exception as e:
            logger.error("ffmpeg 转码失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    # do gc
    source.close()
    del source

    return sample
