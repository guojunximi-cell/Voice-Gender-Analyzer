import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from backend.services.audio_analyser.seg_analyser import AnalyseResultItem


logger = logging.getLogger(__file__)


def do_statics(analyse_results: list[AnalyseResultItem]):
    tfs = sum(r.duration for r in analyse_results if r.label == "female")
    tms = sum(r.duration for r in analyse_results if r.label == "male")

    total_voice_sec = tms + tfs
    female_ratio = (tms / total_voice_sec) if total_voice_sec > 0 else 0.0

    ps, durs = zip(
        (r.confidence, r.duration)
        for r in analyse_results
        if r.confidence and r.label in ("female", "male")
    )
    overall_confidence = float(np.average(ps, weights=durs))

    # F0: 按时长加权均值
    freqs, durs, gss, vfss = zip(
        *(
            (
                r.acoustics["f0_median_hz"],
                r.duration,
                r.acoustics["gender_score"],
                r.acoustics["voiced_frames"],
            )
            for r in analyse_results
            if r.acoustics
        )
    )
    overall_f0 = float(np.average(freqs, weights=durs))

    overall_gender_score = float(np.average(gss, weights=vfss))

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
        "analysis": analyse_results,
    }
