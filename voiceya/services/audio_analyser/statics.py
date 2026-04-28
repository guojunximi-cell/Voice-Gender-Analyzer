from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from typing import Literal

    from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem


logger = logging.getLogger(__name__)


def do_statics(analyse_results: list[AnalyseResultItem]):
    durations: dict[Literal["female", "male"], float] = defaultdict(lambda: 0.0)
    confidences: list[tuple[float, float]] = []
    acoustics: list[tuple[float, float, float, int]] = []

    for r in analyse_results:
        if r.label not in ("female", "male"):
            continue

        durations[r.label] += r.duration

        if r.confidence:
            confidences.append((r.confidence, r.duration))

        if r.acoustics:
            acoustics.append(
                (
                    r.acoustics["f0_median_hz"],
                    r.duration,
                    r.acoustics["gender_score"],
                    r.acoustics["voiced_frames"],
                )
            )

    overall_confidence = 0.0
    overall_f0 = 0.0
    overall_gender_score = 0.0
    female_ratio = 0.0

    total_voice_sec = sum(dur for _, dur in durations.items())
    if total_voice_sec:
        female_ratio = (durations["female"] / total_voice_sec)

    if confidences:
        narr = np.array(confidences)
        overall_confidence = float(np.average(narr[:, 0], weights=narr[:, 1]))
        logger.info(
            "confidence dist — n=%d mean=%.3f std=%.3f p10/p50/p90=[%.2f,%.2f,%.2f] hi(>0.9)=%d lo(<0.1)=%d",
            len(narr),
            narr[:, 0].mean(),
            narr[:, 0].std(),
            float(np.percentile(narr[:, 0], 10)),
            float(np.percentile(narr[:, 0], 50)),
            float(np.percentile(narr[:, 0], 90)),
            int(np.sum(narr[:, 0] > 0.9)),
            int(np.sum(narr[:, 0] < 0.1)),
        )

    # F0 / gender_score: 按时长 / voiced_frames 加权
    if acoustics:
        narr = np.array(acoustics)
        overall_f0 = float(np.average(narr[:, 0], weights=narr[:, 1]))
        if np.any(narr[:, 3]):
            overall_gender_score = float(np.average(narr[:, 2], weights=narr[:, 3]))

    return {
        "status": "success",
        "summary": {
            "total_female_time_sec": durations["female"],
            "total_male_time_sec": durations["male"],
            "female_ratio": round(female_ratio, 4),
            "overall_f0_median_hz": round(overall_f0),
            "overall_gender_score": round(overall_gender_score, 1),
            "overall_confidence": round(overall_confidence, 4),
            "dominant_label": ("female" if female_ratio >= 0.5 else "male")
            if total_voice_sec > 0
            else None,
        },
        "analysis": [r.model_dump() for r in analyse_results],
    }
