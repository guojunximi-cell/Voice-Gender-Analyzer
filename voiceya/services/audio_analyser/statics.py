from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem


logger = logging.getLogger(__file__)


def do_statics(analyse_results: list[AnalyseResultItem]):
    tfs = sum(r.duration for r in analyse_results if r.label == "female")
    tms = sum(r.duration for r in analyse_results if r.label == "male")

    total_voice_sec = tms + tfs
    female_ratio = (tfs / total_voice_sec) if total_voice_sec > 0 else 0.0

    conf_pairs = [
        (r.confidence, r.duration)
        for r in analyse_results
        if r.confidence and r.label in ("female", "male")
    ]
    if conf_pairs:
        ps, confs_durs = zip(*conf_pairs)
        overall_confidence = float(np.average(ps, weights=confs_durs))
    else:
        overall_confidence = 0.0

    # F0 / gender_score: 按时长 / voiced_frames 加权
    acoustic_rows = [
        (
            r.acoustics["f0_median_hz"],
            r.duration,
            r.acoustics["gender_score"],
            r.acoustics["voiced_frames"],
        )
        for r in analyse_results
        if r.acoustics
    ]
    if acoustic_rows:
        freqs, durs_f0, gss, vfss = zip(*acoustic_rows)
        overall_f0 = float(np.average(freqs, weights=durs_f0))
        overall_gender_score = float(np.average(gss, weights=vfss)) if sum(vfss) else 0.0
    else:
        overall_f0 = 0.0
        overall_gender_score = 0.0

    return {
        "status": "success",
        "summary": {
            "total_female_time_sec": tfs,
            "total_male_time_sec": tms,
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
