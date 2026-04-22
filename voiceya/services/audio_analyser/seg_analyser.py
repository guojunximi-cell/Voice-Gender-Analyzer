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

logger = logging.getLogger(__name__)


class AnalyseResultItem(BaseModel):
    label: str
    start_time: float
    end_time: float
    duration: float  # = end_time - start_time
    confidence: float | None = None  # = seg_item[3] if len(seg_item) > 3 else None
    confidence_frames: list[float] | None = None  # = seg_item[4] if len(seg_item) > 4 else None
    acoustics: dict | None = None


def _is_analyzable(label: str, duration: float) -> bool:
    # Engine B 只对够长的有声段抽声学特征；短段或非语音段 F0/共振峰都不稳。
    return label in ("female", "male") and duration >= 0.5


async def do_analyse_segments(
    sample: BytesIO,
    segmentation_results: list[tuple],
    publish: PublisherT,
    end_pct: int = 95,
):
    # ── 提前将完整音频加载入内存，避免在循环中重复 I/O 读取 ────────────
    start_pct = 55
    await publish(
        ProgressSSE(pct=start_pct, msg="鸭鸭正在载入音频…", msg_key="progress.loadAudio")
    )
    try:
        logger.info("正在让 librosa 读取音频…")
        y_full, sr_full = await asyncio.to_thread(librosa.load, sample, sr=None, mono=True)

    except Exception as e:
        logger.error("librosa 读取音频失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    total_voiced = sum(
        1 for s in segmentation_results if _is_analyzable(s[0], s[2] - s[1])
    )
    span = max(end_pct - start_pct, 0)

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

        # 丢掉短时非语音碎屑，避免时间轴被噪声挤满。
        if r.label not in ("female", "male") and r.duration < 0.5:
            continue

        # 进度计数与声学分析严格对齐：只对 _is_analyzable 的段推进进度，
        # 否则 i 会越过 total_voiced，百分比冲破 95% 留下样式 bug。
        if _is_analyzable(r.label, r.duration):
            i += 1
            pct = start_pct + round(span * i / max(total_voiced, 1), 1)
            await publish(
                ProgressSSE(
                    pct=round(pct),
                    msg=f"鸭鸭在分析第 {i}/{total_voiced} 段…",
                    msg_key="progress.analyseSegment",
                    msg_params={"i": i, "total": total_voiced},
                )
            )

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
