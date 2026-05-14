"""Standalone tests for voiceya/services/audio_analyser/audio_gate.py.

Run: ``python tests/test_audio_gate.py`` from the repo root (no pytest needed).
Exit code 0 = all pass; any AssertionError propagates with the test name.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
import traceback
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException  # noqa: E402

from voiceya.services.audio_analyser import do_analyse  # noqa: E402
from voiceya.services.audio_analyser.audio_gate import (  # noqa: E402
    CLIPPING_RATIO_MAX,
    RMS_DBFS_MIN,
    VOICED_RATIO_MIN,
    audio_gate,
)

SR = 16000


def _voiced_speechlike(seconds: float, amp: float = 0.3) -> np.ndarray:
    """Tone burst（200 Hz 正弦），能量稳定足以被 librosa.effects.split 识别为活动段。"""
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds), dtype=np.float32)


def _codes(violations: list[dict]) -> set[str]:
    return {v["code"] for v in violations}


# ── Tests ───────────────────────────────────────────────────────────


def test_happy_path_pass():
    """1.5 s 正弦 + 0.5 s 静音：voiced_ratio ≈ 0.75，RMS ≈ -13 dBFS，无削波。"""
    x = np.concatenate([_voiced_speechlike(1.5), _silence(0.5)])
    out = audio_gate(x, SR)
    assert out == [], f"expected pass, got {out}"


def test_clipping_triggers_only_clipping():
    """正常正弦上把首 1.5% 样本拉到 1.0 → 单独触发 clipping，其余检查仍通过。"""
    x = _voiced_speechlike(2.0, amp=0.5)
    n_clip = int(0.015 * x.size)
    x[:n_clip] = 1.0
    out = audio_gate(x, SR)
    codes = _codes(out)
    assert "clipping" in codes, f"expected clipping, got {codes}"
    assert "too_quiet" not in codes
    assert "insufficient_voicing" not in codes
    clip = next(v for v in out if v["code"] == "clipping")
    assert clip["value"] > CLIPPING_RATIO_MAX
    assert clip["threshold"] == CLIPPING_RATIO_MAX


def test_quiet_input_triggers_too_quiet():
    """整段乘 1e-4 → RMS 必触发 too_quiet（voiced 也可能连带触发，不强制 only）。"""
    x = (_voiced_speechlike(2.0, amp=0.5) * 1e-4).astype(np.float32)
    out = audio_gate(x, SR)
    codes = _codes(out)
    assert "too_quiet" in codes, f"expected too_quiet, got {codes}"
    assert "clipping" not in codes
    rms_v = next(v for v in out if v["code"] == "too_quiet")
    assert rms_v["value"] is not None
    assert rms_v["value"] < RMS_DBFS_MIN


def test_mostly_silent_triggers_insufficient_voicing():
    """0.1s 正弦 + 1.9s 静音 → voiced_ratio ≈ 0.05 必触发 insufficient_voicing。

    背景能量太低也会带出 too_quiet，这是物理上必然的连带，不强制只命中一条。
    """
    x = np.concatenate([_voiced_speechlike(0.1, amp=0.5), _silence(1.9)])
    out = audio_gate(x, SR)
    codes = _codes(out)
    assert "insufficient_voicing" in codes, f"expected insufficient_voicing, got {codes}"
    assert "clipping" not in codes
    voiced_v = next(v for v in out if v["code"] == "insufficient_voicing")
    assert voiced_v["value"] < VOICED_RATIO_MIN


def test_threshold_boundary_passes():
    """value == threshold 应当通过（语义：严格越界才拒）。

    锁死 `>` / `<` 的语义，防止有人改成 `>=` / `<=` 把恰好达标的录音拒掉。
    用 clipping 演示——它能精确构造（80 / 16000 = 0.005 整除）。
    """
    x = _voiced_speechlike(1.0, amp=0.5)
    n_clip = int(round(CLIPPING_RATIO_MAX * x.size))
    assert n_clip / x.size == CLIPPING_RATIO_MAX, "fixture invariant：要能精确等阈值"
    x[:n_clip] = 1.0
    out = audio_gate(x, SR)
    assert "clipping" not in _codes(out), f"边界值不应拒绝，got {out}"


def test_violations_carry_i18n_key():
    """每条 violation 都带稳定的 i18n_key，前端可按 key 翻译。"""
    # 削波 + 静音两条都触发，挑出 i18n_key 验证
    x = _voiced_speechlike(2.0, amp=0.5)
    n_clip = int(0.05 * x.size)
    x[:n_clip] = 1.0
    out_clip = audio_gate(x, SR)
    assert any(v.get("i18n_key") == "audioGate.clipping" for v in out_clip)

    x_silent = np.zeros(int(SR * 1), dtype=np.float32)
    out_silent = audio_gate(x_silent, SR)
    keys = {v.get("i18n_key") for v in out_silent}
    assert "audioGate.silence" in keys
    assert "audioGate.insufficientVoicing" in keys


def test_pure_zero_multi_violation():
    """纯零数组：too_quiet（-inf）+ insufficient_voicing 同时触发。"""
    x = np.zeros(int(SR * 2), dtype=np.float32)
    out = audio_gate(x, SR)
    codes = _codes(out)
    assert codes == {"too_quiet", "insufficient_voicing"}, f"got {codes}"
    rms_v = next(v for v in out if v["code"] == "too_quiet")
    # -inf 序列化不友好，模块里把它降级成 None
    assert rms_v["value"] is None
    assert "静音" in rms_v["message"]


def test_empty_array_no_crash():
    """0 长度数组：不抛异常，按"没声音"处理。"""
    x = np.zeros(0, dtype=np.float32)
    out = audio_gate(x, SR)
    codes = _codes(out)
    # 空数组里没有任何 |x| >= 0.99 的样本，不命中 clipping
    assert "clipping" not in codes
    assert "too_quiet" in codes
    assert "insufficient_voicing" in codes


def _make_wav_bytes(x: np.ndarray, sr: int) -> io.BytesIO:
    """合成一段 PCM16 WAV BytesIO，可被 av.open 正常解码。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        clipped = np.clip(x, -1.0, 1.0)
        w.writeframes((clipped * 32767).astype(np.int16).tobytes())
    buf.seek(0)
    return buf


async def _noop_publish(_event):
    return None


def test_integration_silence_rejected_by_do_analyse():
    """端到端：do_analyse 收到全 0 WAV → HTTPException(400)，detail 是结构化 JSON。"""
    wav = _make_wav_bytes(np.zeros(SR * 2, dtype=np.float32), SR)
    try:
        asyncio.run(do_analyse(wav, _noop_publish))
        raise AssertionError("expected HTTPException, got success")
    except HTTPException as e:
        assert e.status_code == 400, f"expected 400, got {e.status_code}"
        # detail 是 JSON 字符串
        payload = json.loads(e.detail)
        assert payload["error_code"] == "audio_quality_rejected"
        codes = {v["code"] for v in payload["violations"]}
        assert "too_quiet" in codes
        assert "insufficient_voicing" in codes
        assert "音频质量不合格" in payload["message"]


def test_integration_clipping_rejected_by_do_analyse():
    """削波严重的 WAV → 走到闸门，HTTPException(400) 命中 clipping。"""
    rng = np.random.default_rng(7)
    x = rng.uniform(-0.4, 0.4, SR * 2).astype(np.float32)
    # 把 5% 样本拉到 ±1.0：远超 0.5% 削波阈
    n_clip = int(0.05 * x.size)
    x[:n_clip] = 1.0
    wav = _make_wav_bytes(x, SR)
    try:
        asyncio.run(do_analyse(wav, _noop_publish))
        raise AssertionError("expected HTTPException, got success")
    except HTTPException as e:
        assert e.status_code == 400, f"expected 400, got {e.status_code}"
        payload = json.loads(e.detail)
        assert payload["error_code"] == "audio_quality_rejected"
        codes = {v["code"] for v in payload["violations"]}
        assert "clipping" in codes


def test_perf_under_50ms():
    """3 s 和 10 s 随机噪声：单次调用 < 50 ms。"""
    rng = np.random.default_rng(42)
    for seconds in (3, 10):
        x = rng.standard_normal(SR * seconds).astype(np.float32) * 0.3
        # 预热一次：librosa.effects.split 首次调用可能有 import/缓存开销
        audio_gate(x, SR)
        t0 = time.perf_counter()
        audio_gate(x, SR)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 50, f"{seconds}s audio: {elapsed_ms:.1f} ms exceeds 50 ms"


# ── Runner ──────────────────────────────────────────────────────────


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
