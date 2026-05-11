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
from voiceya.services.audio_analyser.f0_panel import compute_f0_panel, prefer_praat_median
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
    # y_full / sr_full 顺手传给下游 (pyin) 避免再 load 一次。
    try:
        y_full, sr_full = await asyncio.to_thread(librosa.load, sample, sr=None, mono=True)
    except Exception as e:
        logger.error("librosa 读取音频失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # librosa.load 默认 float64，闸门约定 float32；这里必然是真转换，不省一次拷贝。
    violations = audio_gate(y_full.astype(np.float32), int(sr_full))
    if violations:
        reasons = "; ".join(v["message"] for v in violations)
        # 警告日志只暴露分类（i18n_key + metric 名），具体测量值（dBFS / clipping_ratio /
        # voiced_ratio）下放到 DEBUG —— 这些数值是用户音频质量指纹，不进生产日志。
        keys = ",".join(v.get("i18n_key") or v.get("metric") or "?" for v in violations)
        logger.warning("音频闸门拒绝 (%d 项): %s", len(violations), keys)
        logger.debug("音频闸门拒绝详情：%s", reasons)
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
    # pct 分配按 scripts/profile_pipeline.py 实测时间份额校准。Engine B 下线后
    # 中段没有持续输出的工作，pct 直接从 A 跳到 C/tail，前端 interp 负责过渡。
    # 配比：with EC → A 40% / C 38% / tail 12%；no EC → A 75% / tail 15%.
    logger.info("Engine A 分析中…")
    await publish(
        ProgressSSE(
            pct=10,
            msg="鸭鸭正在聆听声纹…（此步骤较慢）",
            msg_key="progress.listening",
        )
    )

    segmentation_results = await do_segmentation(sample)

    # do_analyse_segments 现在只是把 ina 元组转 pydantic 模型，<1ms；不再发
    # progress，因为没什么可观察的工作量。
    analyse_results = await do_analyse_segments(y_full, int(sr_full), segmentation_results, publish)

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
        await publish(ProgressSSE(pct=50, msg=msg, msg_key=msg_key))
        sample.seek(0)
        audio_bytes = sample.read()
        engine_c_summary = await run_engine_c(
            audio_bytes, analyse_results, mode=mode, script=script, language=language
        )
        almost_done_pct = 92
    else:
        almost_done_pct = 85

    # ── 全局汇总统计：pyin + statics + advice ──────────────
    # pyin (compute_f0_panel) 是 tail 里最重的一块（30–60s 音频上 0.5–2s）。
    # 算一次后塞给 do_statics 当 overall_f0_median_hz，再传给 compute_advice
    # 当 f0_panel——避免在 advice 里重复跑一次 pyin。
    await publish(
        ProgressSSE(pct=almost_done_pct, msg="鸭鸭快好了…", msg_key="progress.almostDone")
    )

    duration_sec = float(len(y_full)) / float(sr_full) if sr_full else 0.0
    f0_panel = await asyncio.to_thread(compute_f0_panel, y_full, int(sr_full), duration_sec)

    # Praat phone-midpoint median (sidecar) is the authoritative F0 source
    # when Engine C ran — pyin remains the source for p25/p75/voiced_dur
    # since Praat doesn't expose those, but median + zone get overridden.
    if engine_c_summary:
        prefer_praat_median(f0_panel, engine_c_summary.get("median_pitch_hz"))

    result = do_statics(analyse_results, f0_median_hz=f0_panel.get("median_hz"))
    summary = result["summary"]
    summary["engine_c"] = engine_c_summary

    summary["advice"] = compute_advice(
        y_full,
        int(sr_full),
        analyse_results,
        duration_sec,
        summary.get("dominant_label"),
        weighted_margin=summary.get("dominant_confidence", 0.0),
        f0_panel=f0_panel,
        engine_c=engine_c_summary,
    )

    # INFO 日志只记录结构事件（任务完成 + Engine C 是否参与），不带任何用户测量值；
    # F0 / gender_score / female_ratio / advice tier 都是用户解析结果，下放到 DEBUG。
    logger.info("分析完成 (Engine C=%s)", "on" if engine_c_summary else "off/skip")
    logger.debug(
        "分析完成详情 — %d 段，F0=%s Hz，性别评分=%s，女性占比=%.3f，advice tier=%s",
        len(analyse_results),
        summary["overall_f0_median_hz"],
        summary["overall_gender_score"],
        summary["female_ratio"],
        summary["advice"]["gating_tier"],
    )

    result["filename"] = "upload"

    return result
