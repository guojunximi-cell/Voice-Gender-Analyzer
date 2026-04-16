from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import librosa
from fastapi import HTTPException
from pydantic import BaseModel

from voiceya.services.audio_analyser.acoustic_analyzer import analyze_segment
from voiceya.services.sse import ProgressSSE

if TYPE_CHECKING:
    from io import BytesIO

    from voiceya.services.events_stream import PublisherT

logger = logging.getLogger(__file__)


class AnalyseResultItem(BaseModel):
    label: str
    start_time: float
    end_time: float
    duration: float  # = end_time - start_time
    confidence: float | None = None  # = seg_item[3] if len(seg_item) > 3 else None
    confidence_frames: list[float] | None = None  # = seg_item[4] if len(seg_item) > 4 else None
    acoustics: dict | None = None


async def do_analyse_segments(
    sample: BytesIO, segmentation_results: list[tuple], publish: PublisherT
):
    # ── 提前将完整音频加载入内存，避免在循环中重复 I/O 读取 ────────────
    await publish(ProgressSSE(pct=55, msg="鸭鸭正在载入音频…"))
    try:
        logger.info("正在让 librosa 读取音频…")
        y_full, sr_full = await asyncio.to_thread(librosa.load, sample, sr=None, mono=True)

    except Exception as e:
        logger.error("librosa 读取音频失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    total_voiced = sum(
        1 for s in segmentation_results if s[0] in ("female", "male") and (s[2] - s[1]) >= 0.5
    )

    i = 0
    results: list[AnalyseResultItem] = list()
    for seg_item in segmentation_results:
        r = AnalyseResultItem(
            label=seg_item[0],
            start_time=seg_item[1],
            end_time=seg_item[2],
            duration=round(seg_item[2] - seg_item[1], 2),
            confidence=round(seg_item[3], 4) if len(seg_item) > 3 else None,
            confidence_frames=seg_item[4] if len(seg_item) > 4 else None,
            acoustics=None,
        )

        if r.label not in ("female", "male") and r.duration < 0.5:
            continue

        i += 1
        pct = 55 + round(40 * i / max(total_voiced, 1), 1)
        await publish(ProgressSSE(pct=round(pct), msg=f"鸭鸭在分析第 {i}/{total_voiced} 段…"))

        start = int(r.start_time * sr_full)
        end = int(r.end_time * sr_full)
        try:
            y_seg = y_full[start:end]
            # numpy ndarray 不能直接当 bool 用（多元素会抛
            # "truth value of an array is ambiguous"），这里只关心切片非空。
            if y_seg.size:
                r.acoustics = await asyncio.to_thread(analyze_segment, y_seg, int(sr_full))

        except Exception as e:
            logger.warning(
                "Engine B 跳过 [%.1f~%.1fs]: %s",
                r.start_time,
                r.end_time,
                e,
            )

        r.start_time = round(r.start_time, 2)
        r.end_time = round(r.end_time, 2)

        results.append(r)

    return results
