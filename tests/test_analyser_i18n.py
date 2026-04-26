"""Standalone tests for the i18n helpers in voiceya/tasks/analyser.py.

Covers the contract that the worker's HTTPException catch relies on:
audio_gate JSON detail → (msg, msg_key, msg_params) for the frontend.
Anything else degrades gracefully to plain msg.

Run: ``python tests/test_analyser_i18n.py`` from the repo root.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException  # noqa: E402

from voiceya.tasks.analyser import (  # noqa: E402
    _gate_violation_params,
    _i18n_from_http_exception,
)


def _gate_detail(violations: list[dict], message: str = "音频质量不合格") -> str:
    return json.dumps(
        {"error_code": "audio_quality_rejected", "violations": violations, "message": message},
        ensure_ascii=False,
    )


# ── _gate_violation_params ──────────────────────────────────────────


def test_params_clipping_ratio_to_pct():
    out = _gate_violation_params({"metric": "clipping_ratio", "value": 0.0123})
    assert out == {"pct": 1.2}, out


def test_params_voiced_ratio_to_pct():
    out = _gate_violation_params({"metric": "voiced_ratio", "value": 0.087})
    assert out == {"pct": 8.7}, out


def test_params_rms_dbfs_to_db():
    out = _gate_violation_params({"metric": "rms_dbfs", "value": -42.34567})
    assert out == {"db": -42.3}, out


def test_params_value_none_returns_none():
    """audio_gate emits value=None when RMS is silent (-inf). No params possible."""
    assert _gate_violation_params({"metric": "rms_dbfs", "value": None}) is None


def test_params_unknown_metric_returns_none():
    assert _gate_violation_params({"metric": "snr_db", "value": 5.0}) is None


# ── _i18n_from_http_exception ───────────────────────────────────────


def test_plain_string_detail_passes_through():
    exc = HTTPException(status_code=500, detail="boom")
    assert _i18n_from_http_exception(exc) == ("boom", None, None)


def test_gate_clipping_extracts_key_and_params():
    detail = _gate_detail(
        [
            {
                "code": "clipping",
                "i18n_key": "audioGate.clipping",
                "metric": "clipping_ratio",
                "value": 0.012,
                "message": "削波严重 (1.2% 样本饱和)",
            }
        ],
        message="音频质量不合格：削波严重 (1.2% 样本饱和)",
    )
    msg, key, params = _i18n_from_http_exception(HTTPException(400, detail))
    assert key == "audioGate.clipping"
    assert params == {"pct": 1.2}
    assert "削波" in msg


def test_gate_silence_yields_key_without_params():
    """value=None (RMS=-inf path) → key present, params None — frontend uses the
    template's literal text without any {db}/{pct} substitution."""
    detail = _gate_detail(
        [
            {
                "code": "too_quiet",
                "i18n_key": "audioGate.silence",
                "metric": "rms_dbfs",
                "value": None,
                "message": "音量过低 (静音)",
            }
        ]
    )
    _msg, key, params = _i18n_from_http_exception(HTTPException(400, detail))
    assert key == "audioGate.silence"
    assert params is None


def test_gate_picks_first_violation_only():
    """Multiple violations (clipping + too_quiet) → first one drives i18n; the
    rest fold into the prebuilt message string."""
    detail = _gate_detail(
        [
            {
                "code": "clipping",
                "i18n_key": "audioGate.clipping",
                "metric": "clipping_ratio",
                "value": 0.05,
                "message": "削波严重",
            },
            {
                "code": "too_quiet",
                "i18n_key": "audioGate.tooQuiet",
                "metric": "rms_dbfs",
                "value": -55.0,
                "message": "音量过低",
            },
        ]
    )
    _msg, key, params = _i18n_from_http_exception(HTTPException(400, detail))
    assert key == "audioGate.clipping"
    assert params == {"pct": 5.0}


def test_gate_empty_violations_falls_through():
    """error_code present but violations missing/empty → no key, no params."""
    detail = _gate_detail([])
    msg, key, params = _i18n_from_http_exception(HTTPException(400, detail))
    assert key is None
    assert params is None
    assert "音频质量不合格" in msg


def test_unrelated_json_detail_passes_through():
    """JSON detail without our error_code → treated as plain text."""
    detail = json.dumps({"error_code": "rate_limited", "retry_after": 30})
    msg, key, params = _i18n_from_http_exception(HTTPException(429, detail))
    assert (key, params) == (None, None)
    assert msg == detail


def test_malformed_json_detail_passes_through():
    msg, key, params = _i18n_from_http_exception(HTTPException(400, "{not json"))
    assert (msg, key, params) == ("{not json", None, None)


def test_non_string_detail_stringified():
    """Starlette permits dict/list detail. We stringify so msg is at least
    serializable for the SSE payload."""
    exc = HTTPException(status_code=400, detail={"foo": "bar"})
    msg, key, params = _i18n_from_http_exception(exc)
    assert (key, params) == (None, None)
    assert "foo" in msg and "bar" in msg


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
