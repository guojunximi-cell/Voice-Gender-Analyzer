"""Tier-1 音频质量闸门：在 Engine B (YIN/LPC/HNR) 之前对整段音频做信号统计判别。

只用 NumPy + librosa，无外部模型。设计成纯函数：返回 violations 列表，
由调用方决定怎么处理（抛 HTTPException / 写日志 / 走告警）。
"""

import librosa
import numpy as np

# Tier 1 阈值——硬编码常量；Tier 2 接入时再统一规划是否上浮到 CFG。
CLIPPING_RATIO_MAX = 0.005  # |x| >= 0.99 占比上限
RMS_DBFS_MIN = -40.0  # 整段 RMS dBFS 下限
VOICED_RATIO_MIN = 0.30  # 活动段时长占比下限
CLIP_THRESHOLD = 0.99  # 削波判定阈值
VAD_TOP_DB = 30  # librosa.effects.split 静音阈


def audio_gate(x: np.ndarray, sr: int) -> list[dict]:
    """Tier-1 音频质量闸门：信号统计层判别。

    Args:
        x: 单声道 float32，已重采样（不在闸门里再做转换）。
        sr: 采样率，仅传给 librosa.effects.split。

    Returns:
        violations 列表；空列表表示通过。每项形如：
          {"code": "clipping", "metric": "clipping_ratio",
           "value": 0.012, "threshold": 0.005,
           "message": "削波严重 (1.2% 样本饱和)"}
    """
    violations: list[dict] = []

    # 1. clipping_ratio
    clip_ratio = float(np.mean(np.abs(x) >= CLIP_THRESHOLD)) if x.size else 0.0
    if clip_ratio > CLIPPING_RATIO_MAX:
        violations.append(
            {
                "code": "clipping",
                "i18n_key": "audioGate.clipping",
                "metric": "clipping_ratio",
                "value": round(clip_ratio, 4),
                "threshold": CLIPPING_RATIO_MAX,
                "message": f"削波严重 ({clip_ratio * 100:.1f}% 样本饱和)",
            }
        )

    # 2. rms_dbfs（空段或纯零兜底为 -inf，对应 too_quiet）
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if x.size else 0.0
    rms_dbfs = 20.0 * np.log10(rms) if rms > 0 else -np.inf
    if rms_dbfs < RMS_DBFS_MIN:
        violations.append(
            {
                "code": "too_quiet",
                "i18n_key": "audioGate.tooQuiet" if np.isfinite(rms_dbfs) else "audioGate.silence",
                "metric": "rms_dbfs",
                "value": round(rms_dbfs, 2) if np.isfinite(rms_dbfs) else None,
                "threshold": RMS_DBFS_MIN,
                "message": (
                    f"音量过低 (RMS {rms_dbfs:.1f} dBFS)"
                    if np.isfinite(rms_dbfs)
                    else "音量过低 (静音)"
                ),
            }
        )

    # 3. voiced_ratio（能量阈 VAD）
    # 全零输入时 librosa.effects.split 因没有参考帧会把整段当作"活动段"，
    # 这里显式按 0 处理——任何 RMS 为 0 的段都不可能"有声"。
    if x.size and rms > 0:
        intervals = librosa.effects.split(x, top_db=VAD_TOP_DB)
        voiced_samples = int(np.sum(intervals[:, 1] - intervals[:, 0])) if intervals.size else 0
        voiced_ratio = voiced_samples / x.size
    else:
        voiced_ratio = 0.0

    if voiced_ratio < VOICED_RATIO_MIN:
        violations.append(
            {
                "code": "insufficient_voicing",
                "i18n_key": "audioGate.insufficientVoicing",
                "metric": "voiced_ratio",
                "value": round(voiced_ratio, 3),
                "threshold": VOICED_RATIO_MIN,
                "message": f"有效语音占比过低 ({voiced_ratio * 100:.0f}%)",
            }
        )

    return violations
