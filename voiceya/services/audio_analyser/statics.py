from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from typing import Literal

    from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem


logger = logging.getLogger(__name__)


def weighted_confidence(
    analyse_results: list[AnalyseResultItem],
    label_filter: str | None = None,
) -> float:
    """Duration-weighted Engine A C1 margin.

    `label_filter=None` → all voiced segments (`female` ∪ `male`); used for
    `summary.overall_confidence`. A specific label → that class only; used for
    `summary.dominant_confidence` and Advice v2's tone-tendency margin. One
    helper means the weighting formula can't drift between callers.
    """
    pairs: list[tuple[float, float]] = []
    for r in analyse_results:
        if r.confidence is None:
            continue
        if label_filter is None:
            if r.label not in ("female", "male"):
                continue
        elif r.label != label_filter:
            continue
        pairs.append((r.confidence, r.duration))
    if not pairs:
        return 0.0
    arr = np.array(pairs)
    return float(np.average(arr[:, 0], weights=arr[:, 1]))


def do_statics(analyse_results: list[AnalyseResultItem]):
    durations: dict[Literal["female", "male"], float] = defaultdict(lambda: 0.0)
    acoustics: list[tuple[float, float, float, int]] = []

    for r in analyse_results:
        if r.label not in ("female", "male"):
            continue

        durations[r.label] += r.duration

        if r.acoustics:
            acoustics.append(
                (
                    r.acoustics["f0_median_hz"],
                    r.duration,
                    r.acoustics["gender_score"],
                    r.acoustics["voiced_frames"],
                )
            )

    overall_f0 = 0.0
    overall_gender_score = 0.0
    female_ratio = 0.0

    total_voice_sec = sum(dur for _, dur in durations.items())
    if total_voice_sec:
        female_ratio = (durations["female"] / total_voice_sec)

    dominant_label = (
        ("female" if female_ratio >= 0.5 else "male") if total_voice_sec > 0 else None
    )

    overall_confidence = weighted_confidence(analyse_results, label_filter=None)
    dominant_confidence = (
        weighted_confidence(analyse_results, label_filter=dominant_label)
        if dominant_label is not None
        else 0.0
    )

    confs = np.array([r.confidence for r in analyse_results if r.confidence is not None and r.label in ("female", "male")])
    if confs.size:
        logger.info(
            "confidence dist — n=%d mean=%.3f std=%.3f p10/p50/p90=[%.2f,%.2f,%.2f] hi(>0.9)=%d lo(<0.1)=%d",
            confs.size,
            confs.mean(),
            confs.std(),
            float(np.percentile(confs, 10)),
            float(np.percentile(confs, 50)),
            float(np.percentile(confs, 90)),
            int(np.sum(confs > 0.9)),
            int(np.sum(confs < 0.1)),
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
            "dominant_confidence": round(dominant_confidence, 4),
            "dominant_label": dominant_label,
        },
        "analysis": [r.model_dump() for r in analyse_results],
    }
