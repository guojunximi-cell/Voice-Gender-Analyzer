from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel

if TYPE_CHECKING:
    from voiceya.services.events_stream import PublisherT  # noqa: F401

logger = logging.getLogger(__name__)


class AnalyseResultItem(BaseModel):
    label: str
    start_time: float
    end_time: float
    duration: float  # = end_time - start_time
    confidence: float | None = None  # = seg_item[3] if len(seg_item) > 3 else None
    confidence_frames: list[float] | None = None  # = seg_item[4] if len(seg_item) > 4 else None
    # acoustics 永远是 None。Engine B (acoustic_analyzer) 已下线；保留字段是为
    # 旧导出的 .vga.json 还能反序列化。前端不再依赖它。
    acoustics: None = None


async def do_analyse_segments(
    y_full: np.ndarray,
    sr_full: int,
    segmentation_results: list[tuple],
    publish: PublisherT,
):
    # Engine B 下线后这里只剩"把 ina 元组转 pydantic 模型 + 丢碎屑"——纯
    # CPU 内存操作，<1ms，无需进度事件，也不再切片做 LPC。signature 还保留
    # publish 形参以便 do_analyse 调用方少改字段，但本函数不再 emit。
    _ = publish  # silence unused-arg lint

    results: list[AnalyseResultItem] = list()
    for seg_item in segmentation_results:
        r = AnalyseResultItem(
            label=seg_item[0],
            start_time=seg_item[1],
            end_time=seg_item[2],
            duration=round(seg_item[2] - seg_item[1], 2),
            confidence=round(seg_item[3], 4) if len(seg_item) > 3 else None,
            confidence_frames=seg_item[4] if len(seg_item) > 4 else None,
        )

        # 丢掉短时非语音碎屑，避免时间轴被噪声挤满。
        if r.label not in ("female", "male") and r.duration < 0.5:
            continue

        r.start_time = round(r.start_time, 2)
        r.end_time = round(r.end_time, 2)

        results.append(r)

    return results
