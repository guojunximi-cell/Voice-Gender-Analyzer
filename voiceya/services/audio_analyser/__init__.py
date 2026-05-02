from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Literal

import librosa
import numpy as np
from fastapi import HTTPException

from voiceya.config import CFG
from voiceya.services.audio_analyser.advice_v2 import compute_advice
from voiceya.services.audio_analyser.audio_gate import audio_gate
from voiceya.services.audio_analyser.audio_tools import normalize_audio_for_analysis
from voiceya.services.audio_analyser.engine_a import do_segmentation
from voiceya.services.audio_analyser.engine_c import run_engine_c
from voiceya.services.audio_analyser.seg_analyser import do_analyse_segments
from voiceya.services.audio_analyser.statics import do_statics
from voiceya.services.sse import ProgressSSE

if TYPE_CHECKING:
    from io import BytesIO

    from voiceya.services.events_stream import PublisherT

logger = logging.getLogger(__name__)


async def do_analyse(
    content: BytesIO,
    publish: PublisherT,
    *,
    mode: Literal["free", "script"] = "free",
    script: str | None = None,
    language: Literal["zh-CN", "en-US", "fr-FR"] = "zh-CN",
):
    """Async generator: yields SSE event strings with real progress, last event has type='result'."""
    sample = await normalize_audio_for_analysis(content, publish)

    # ── 提前 load + Tier-1 闸门 ───────────────────────────
    # 闸门挡在 Engine A 之前，纯噪声/静音/削波样本直接拒，省 5–30s 的 VAD 时间。
    # y_full / sr_full 顺手传给 Engine B，避免下游再 load 一次。
    try:
        y_full, sr_full = await asyncio.to_thread(librosa.load, sample, sr=None, mono=True)
    except Exception as e:
        logger.error("librosa 读取音频失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # librosa.load 默认 float64，闸门约定 float32；这里必然是真转换，不省一次拷贝。
    violations = audio_gate(y_full.astype(np.float32), int(sr_full))
    if violations:
        reasons = "; ".join(v["message"] for v in violations)
        logger.warning("音频闸门拒绝：%s", reasons)
        raise HTTPException(
            status_code=400,
            detail=json.dumps(
                {
                    "error_code": "audio_quality_rejected",
                    "violations": violations,
                    "message": f"音频质量不合格：{reasons}",
                },
                ensure_ascii=False,
            ),
        )

    # Engine A 仍以 BytesIO 形式喂给 inaSpeechSegmenter，要把流游标退回起点。
    sample.seek(0)

    # ── Engine A: 时间分段 ─────────────────────────────────
    logger.info("Engine A 分析中…")
    await publish(
        ProgressSSE(
            pct=10,
            msg="鸭鸭正在聆听声纹…（此步骤较慢）",
            msg_key="progress.listening",
        )
    )

    segmentation_results = await do_segmentation(sample)

    # ── Engine B: 声学分析（仅对有声语音段）────────────
    await publish(
        ProgressSSE(pct=50, msg="鸭鸭听完了！正在整理笔记…", msg_key="progress.organizing")
    )

    # 开 Engine C 时给"开小灶"阶段留一大段进度预算（72→94）——它是最慢的一环，
    # 进度太靠右会让用户以为马上就好，其实还要等 ASR + MFA + Praat 跑完。
    seg_end_pct = 70 if CFG.engine_c_enabled else 95
    analyse_results = await do_analyse_segments(
        y_full, int(sr_full), segmentation_results, publish, end_pct=seg_end_pct
    )

    # ── Engine C: 进阶分析（feature-flagged，默认关）────────
    engine_c_summary = None
    if CFG.engine_c_enabled:
        # script 模式跳过 ASR，直接把稿子喂给 MFA——文案同步换掉。
        if mode == "script":
            msg = "鸭鸭照着稿子逐字对齐…"
            msg_key = "progress.engineCScript"
        else:
            msg = "鸭鸭开小灶做进阶分析…"
            msg_key = "progress.engineCFree"
        await publish(ProgressSSE(pct=72, msg=msg, msg_key=msg_key))
        sample.seek(0)
        audio_bytes = sample.read()
        engine_c_summary = await run_engine_c(
            audio_bytes, analyse_results, mode=mode, script=script, language=language
        )

    # ── 全局汇总统计 ───────────────────────────────────────
    await publish(ProgressSSE(pct=98, msg="鸭鸭快好了…", msg_key="progress.almostDone"))

    result = do_statics(analyse_results)
    summary = result["summary"]
    summary["engine_c"] = engine_c_summary

    duration_sec = float(len(y_full)) / float(sr_full) if sr_full else 0.0
    summary["advice"] = compute_advice(
        y_full,
        int(sr_full),
        analyse_results,
        duration_sec,
        summary.get("dominant_label"),
        weighted_margin=summary.get("dominant_confidence", 0.0),
    )

    logger.info(
        "分析完成 — %d 段，F0=%s Hz，性别评分=%s，女性占比=%.3f，Engine C=%s，advice tier=%s",
        len(analyse_results),
        summary["overall_f0_median_hz"],
        summary["overall_gender_score"],
        summary["female_ratio"],
        "on" if engine_c_summary else "off/skip",
        summary["advice"]["gating_tier"],
    )

    result["filename"] = "upload"

    return result
