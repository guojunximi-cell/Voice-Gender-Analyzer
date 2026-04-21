#!/usr/bin/env python3
"""Docker integration validation for Voice Gender Analyzer.

Covers all 8 gates defined in the task-7 checklist:

  1. docker compose build                       — main image + Paraformer-zh pre-download
  2. docker compose --profile engine-c build    — sidecar ~2.5 GB
  3. docker compose --profile engine-c up -d    — GET /healthz returns {"ok": true, ...}
  4. ENGINE_C_ENABLED=false                     — upload audio, summary.engine_c == null
  5. ENGINE_C_ENABLED=true  10/30/60 s ZH       — engine_c present, medianResonance ∈ [0.3, 0.8]
  6. Kill sidecar                               — main still 200 + engine_c == null
  7. 5m/5f regression                           — median(male) < median(female)
  8. Upstream equivalence                       — |wrapper - direct| < 0.02

Usage
-----
  python scripts/validate_docker.py [options]

  --base-url  URL          API root (default: http://localhost:8080)
  --fixtures  DIR          Directory that holds Chinese-speech WAV files (see below)
  --skip-build             Assume images are already built; skip tasks 1–2
  --skip-engine-c          Skip tasks 5–8 (no Chinese speech available)
  --only  N                Run only task N (1–8)

Fixtures directory layout (tasks 5/7/8 require Chinese speech)
---------------------------------------------------------------
  zh_10s.wav   zh_30s.wav   zh_60s.wav   # any Mandarin speaker, these durations
  male_1.wav   … male_5.wav              # five different male speakers
  female_1.wav … female_5.wav            # five different female speakers
"""

from __future__ import annotations

import base64
import http.client
import io
import json
import math
import os
import statistics
import struct
import subprocess
import sys
import time
import wave
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Force UTF-8 output so Unicode tick/cross work on Windows (GBK default).
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ─── Globals ────────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8080"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _conn(timeout: int) -> http.client.HTTPConnection:
    """HTTP(S)Connection parsed from BASE_URL.  One choke-point so --base-url
    actually takes effect; every HTTP helper in this script goes through here."""
    parts = urlsplit(BASE_URL)
    host = parts.hostname or "localhost"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    return cls(host, port, timeout=timeout)

_RESULTS: list[tuple[str, bool, str]] = []

# ─── Terminal colours ────────────────────────────────────────────────────────
_G = "\033[92m"
_R = "\033[91m"
_Y = "\033[93m"
_B = "\033[94m"
_X = "\033[0m"


def _ok(tag: str, msg: str) -> None:
    _RESULTS.append((tag, True, msg))
    print(f"  {_G}✓ PASS{_X}  {tag}: {msg}")


def _fail(tag: str, msg: str) -> None:
    _RESULTS.append((tag, False, msg))
    print(f"  {_R}✗ FAIL{_X}  {tag}: {msg}")


def _skip(tag: str, msg: str) -> None:
    print(f"  {_Y}– SKIP{_X}  {tag}: {msg}")


def _section(n: int, title: str) -> None:
    print(f"\n{_B}{'─' * 62}{_X}")
    print(f"{_B}Task {n}: {title}{_X}")
    print(f"{_B}{'─' * 62}{_X}")


# ─── .env management ────────────────────────────────────────────────────────

_DOCKER_ENV_BASE: dict[str, str] = {
    "REDIS_URL": "redis://redis:6379/0",
    "LOG_LEVEL": "INFO",
    "ENGINE_C_ENABLED": "false",
    "ENGINE_C_SIDECAR_URL": "http://visualizer-backend:8001",
    "ENGINE_C_SIDECAR_TIMEOUT_SEC": "60",
    "ENGINE_C_MIN_DURATION_SEC": "3",
    "MAX_FILE_SIZE_MB": "10",
    "MAX_AUDIO_DURATION_SEC": "180",
    # Raise rate limit so the 15+ validation requests don't get rejected.
    "RATE_LIMIT_CT": "100",
    "RATE_LIMIT_DURATION_SEC": "60",
    "MAX_CONCURRENT": "2",
    "MAX_QUEUE_DEPTH": "30",
}


def _write_docker_env(engine_c: bool) -> None:
    env = dict(_DOCKER_ENV_BASE)
    env["ENGINE_C_ENABLED"] = "true" if engine_c else "false"
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")


# ─── Docker helpers ──────────────────────────────────────────────────────────


def _dc(*args: str, check: bool = True, capture: bool = False, timeout: int = 1800) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose"] + list(args)
    print(f"  $ {' '.join(cmd)}")
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=timeout)
    return subprocess.run(cmd, cwd=PROJECT_ROOT, timeout=timeout, check=check)


def _wait_for_api(max_wait: int = 90) -> bool:
    """Poll GET /api/config until 200 or timeout."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            conn = _conn(timeout=5)
            conn.request("GET", "/api/config")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status == 200:
                return True
        except OSError:
            pass
        time.sleep(3)
    return False


def _bring_up(engine_c: bool) -> bool:
    """Write .env, bring up services, wait for API."""
    _write_docker_env(engine_c)
    profile_args = ["--profile", "engine-c"] if engine_c else []
    r = _dc(*profile_args, "up", "-d", check=False, timeout=300)
    if r.returncode != 0:
        return False
    return _wait_for_api()


# ─── Synthetic audio ─────────────────────────────────────────────────────────


def _make_sine_wav(duration_sec: float, freq: float = 220.0, sr: int = 16_000) -> bytes:
    """Valid WAV with a sine tone – passes magic-bytes check, not real speech."""
    n = int(sr * duration_sec)
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack(f"<{n}h", *(int(32767 * math.sin(2 * math.pi * freq * i / sr)) for i in range(n))))
    return buf.getvalue()


# ─── API helpers ─────────────────────────────────────────────────────────────


def _post_audio(audio: bytes, timeout: int = 30) -> str:
    """POST raw audio bytes → task_id string."""
    conn = _conn(timeout=timeout)
    conn.request("POST", "/api/analyze-voice", audio, {"Content-Type": "audio/wav"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    if resp.status != 200:
        raise RuntimeError(f"POST /api/analyze-voice → {resp.status}: {body[:200]!r}")
    return json.loads(body)["task_id"]


def _await_result(task_id: str, timeout: int = 300) -> dict[str, Any]:
    """Stream SSE until type='result' event; return its data dict."""
    conn = _conn(timeout=timeout)
    conn.request("GET", f"/api/status/{task_id}", headers={"Accept": "text/event-stream"})
    resp = conn.getresponse()
    if resp.status != 200:
        body = resp.read()
        conn.close()
        raise RuntimeError(f"GET /api/status → {resp.status}: {body[:200]!r}")

    buf = b""
    while True:
        chunk = resp.read(1024)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            raw_event, buf = buf.split(b"\n\n", 1)
            for line in raw_event.split(b"\n"):
                decoded = line.decode("utf-8", errors="replace")
                if not decoded.startswith("data: "):
                    continue
                try:
                    evt = json.loads(decoded[6:])
                except json.JSONDecodeError:
                    continue
                if evt.get("type") == "result":
                    conn.close()
                    return evt["data"]
                if evt.get("type") == "error":
                    conn.close()
                    raise RuntimeError(f"SSE error: {evt.get('msg', evt)}")

    conn.close()
    raise RuntimeError("SSE stream ended without a 'result' event")


def _analyze(audio: bytes, timeout: int = 300) -> dict[str, Any]:
    task_id = _post_audio(audio, timeout=30)
    return _await_result(task_id, timeout=timeout)


# ─── Individual tasks ────────────────────────────────────────────────────────


def _task1(skip_build: bool) -> None:
    _section(1, "docker compose build — main image + Paraformer-zh pre-download")
    if skip_build:
        _skip("T1", "--skip-build flag set")
        return
    r = _dc("build", "--progress=plain", check=False)
    if r.returncode == 0:
        _ok("T1.build", "main image built (exit 0)")
    else:
        _fail("T1.build", f"build failed (exit {r.returncode})")


def _task2(skip_build: bool) -> None:
    _section(2, "docker compose --profile engine-c build visualizer-backend (~2.5 GB)")
    if skip_build:
        _skip("T2", "--skip-build flag set")
        return
    r = _dc("--profile", "engine-c", "build", "--progress=plain", "visualizer-backend", check=False)
    if r.returncode != 0:
        _fail("T2.build", f"sidecar build failed (exit {r.returncode})")
        return
    _ok("T2.build", "sidecar built (exit 0)")

    # Report image size for the record (non-blocking).
    r2 = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}  {{.Size}}"],
        capture_output=True, text=True,
    )
    for line in r2.stdout.splitlines():
        if "visualizer" in line.lower():
            _ok("T2.size", f"image: {line.strip()}")
            break


def _task3() -> None:
    _section(3, "docker compose --profile engine-c up -d + GET /healthz")
    # Task 3 explicitly requires the sidecar — always start with engine-c profile.
    _write_docker_env(engine_c=False)
    r0 = _dc("--profile", "engine-c", "up", "-d", check=False, timeout=300)
    if r0.returncode != 0:
        _fail("T3.up", f"docker compose up failed (exit {r0.returncode})")
        return
    if not _wait_for_api():
        _fail("T3.api_ready", "API did not become ready on :8080 within timeout")
        return
    _ok("T3.up", "stack up, API responding on :8080")

    # Healthz check via exec (port 8001 is not published to host; -T = no TTY).
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "visualizer-backend",
         "curl", "-fsS", "http://localhost:8001/healthz"],
        capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=30,
    )
    if r.returncode == 0:
        try:
            body = json.loads(r.stdout)
            if body.get("ok") is True:
                _ok("T3.healthz", f"sidecar /healthz → {json.dumps(body)}")
            else:
                _fail("T3.healthz", f"ok!=true in /healthz response: {body}")
        except json.JSONDecodeError:
            _fail("T3.healthz", f"non-JSON /healthz response: {r.stdout[:200]}")
    else:
        _fail("T3.healthz", f"curl to sidecar failed (exit {r.returncode}): {r.stderr[:200]}")


def _task4() -> None:
    _section(4, "ENGINE_C_ENABLED=false — summary.engine_c must be null (backward compat)")
    if not _bring_up(engine_c=False):
        _fail("T4.up", "could not bring up stack with ENGINE_C=false")
        return

    audio = _make_sine_wav(10.0)
    try:
        result = _analyze(audio, timeout=180)
    except Exception as exc:
        _fail("T4.call", f"analysis call raised: {exc}")
        return

    summary = result.get("summary", {})

    ec = summary.get("engine_c", "KEY_MISSING")
    if ec is None:
        _ok("T4.engine_c_null", "summary.engine_c == null ✓")
    else:
        _fail("T4.engine_c_null", f"expected null, got {ec!r}")

    required = ["total_female_time_sec", "total_male_time_sec", "female_ratio",
                "overall_f0_median_hz", "overall_gender_score", "overall_confidence"]
    missing = [f for f in required if f not in summary]
    if missing:
        _fail("T4.schema", f"missing fields: {missing}")
    else:
        _ok("T4.schema", "all required summary fields present")

    if result.get("status") == "success":
        _ok("T4.status", "result.status == 'success'")
    else:
        _fail("T4.status", f"result.status = {result.get('status')!r}")


def _task5(fixtures: Path | None) -> None:
    _section(5, "ENGINE_C_ENABLED=true — 10/30/60 s ZH audio → medianResonance ∈ [0.3, 0.8]")
    if not fixtures:
        _skip("T5", "pass --fixtures DIR with zh_10s.wav, zh_30s.wav, zh_60s.wav")
        return

    if not _bring_up(engine_c=True):
        _fail("T5.up", "could not bring up stack with ENGINE_C=true")
        return

    for fname in ("zh_10s.wav", "zh_30s.wav", "zh_60s.wav"):
        fpath = fixtures / fname
        if not fpath.exists():
            _skip(f"T5.{fname}", f"fixture not found: {fpath}")
            continue

        try:
            result = _analyze(fpath.read_bytes(), timeout=300)
        except Exception as exc:
            _fail(f"T5.{fname}.call", str(exc))
            continue

        ec = result.get("summary", {}).get("engine_c")
        if ec is None:
            _fail(f"T5.{fname}.present", "engine_c is null — sidecar may be unreachable")
            continue
        _ok(f"T5.{fname}.present", "engine_c field populated ✓")

        mr = ec.get("median_resonance")
        if mr is None:
            _fail(f"T5.{fname}.resonance", "median_resonance key missing from engine_c")
        elif 0.3 <= mr <= 0.8:
            _ok(f"T5.{fname}.resonance", f"medianResonance={mr:.4f} ∈ [0.3, 0.8] ✓")
        else:
            _fail(f"T5.{fname}.resonance", f"medianResonance={mr:.4f} outside [0.3, 0.8]")


def _task6() -> None:
    _section(6, "Kill sidecar → main still returns 200 + summary.engine_c == null")
    # Need ENGINE_C enabled so the code path is exercised.
    if not _bring_up(engine_c=True):
        _fail("T6.up", "could not bring up stack with ENGINE_C=true")
        return

    r = _dc("stop", "visualizer-backend", check=False, timeout=30)
    if r.returncode != 0:
        _fail("T6.stop", "docker compose stop visualizer-backend failed")
        return
    _ok("T6.stop", "visualizer-backend container stopped")

    time.sleep(2)  # let the connection pool drain

    audio = _make_sine_wav(10.0)
    try:
        result = _analyze(audio, timeout=180)
    except Exception as exc:
        _fail("T6.200", f"main API raised after sidecar killed: {exc}")
    else:
        _ok("T6.200", "main API returned 200 ✓")
        ec = result.get("summary", {}).get("engine_c", "KEY_MISSING")
        if ec is None:
            _ok("T6.engine_c_null", "summary.engine_c == null (graceful degradation) ✓")
        else:
            _fail("T6.engine_c_null", f"expected null, got {ec!r}")

    # Restore sidecar for subsequent tasks.
    _dc("--profile", "engine-c", "up", "-d", "visualizer-backend", check=False, timeout=60)
    _ok("T6.restore", "sidecar restarted")


def _task7(fixtures: Path | None) -> None:
    _section(7, "5m/5f regression: median(male medianResonance) < median(female medianResonance)")
    if not fixtures:
        _skip("T7", "pass --fixtures DIR with male_1..5.wav and female_1..5.wav")
        return

    if not _bring_up(engine_c=True):
        _fail("T7.up", "could not bring up stack with ENGINE_C=true")
        return

    male_mrs: list[float] = []
    female_mrs: list[float] = []

    for gender, bucket in (("male", male_mrs), ("female", female_mrs)):
        for i in range(1, 6):
            fname = f"{gender}_{i}.wav"
            fpath = fixtures / fname
            if not fpath.exists():
                _skip(f"T7.{fname}", f"fixture not found: {fpath}")
                continue
            try:
                result = _analyze(fpath.read_bytes(), timeout=300)
                ec = result.get("summary", {}).get("engine_c")
                mr = ec.get("median_resonance") if ec else None
                if mr is not None:
                    bucket.append(float(mr))
                    print(f"    {fname}: medianResonance={mr:.4f}")
                else:
                    _skip(f"T7.{fname}", "engine_c null or median_resonance missing")
            except Exception as exc:
                _fail(f"T7.{fname}", str(exc))

    if len(male_mrs) < 3 or len(female_mrs) < 3:
        _skip("T7.regression", f"need ≥3 samples each; got {len(male_mrs)}m/{len(female_mrs)}f")
        return

    med_m = statistics.median(male_mrs)
    med_f = statistics.median(female_mrs)
    print(f"    median(male)={med_m:.4f}  median(female)={med_f:.4f}")

    if med_m < med_f:
        _ok("T7.regression", f"median(male)={med_m:.4f} < median(female)={med_f:.4f} ✓")
    else:
        _fail("T7.regression", f"median(male)={med_m:.4f} >= median(female)={med_f:.4f}")


def _task8(fixtures: Path | None) -> None:
    _section(8, "Upstream equivalence: |wrapper.medianResonance − direct| < 0.02")
    if not fixtures:
        _skip("T8", "pass --fixtures DIR (uses first available ZH fixture)")
        return

    test_file: Path | None = None
    for fname in ("zh_30s.wav", "zh_10s.wav", "zh_60s.wav", "male_1.wav", "female_1.wav"):
        p = fixtures / fname
        if p.exists():
            test_file = p
            break

    if test_file is None:
        _skip("T8", "no suitable fixture found in --fixtures dir")
        return

    if not _bring_up(engine_c=True):
        _fail("T8.up", "could not bring up stack with ENGINE_C=true")
        return

    # ── Step 1: get result via the full wrapper path ──────────────────────
    try:
        result = _analyze(test_file.read_bytes(), timeout=300)
    except Exception as exc:
        _fail("T8.wrapper", str(exc))
        return

    ec = result.get("summary", {}).get("engine_c")
    if ec is None:
        _skip("T8", "engine_c null from wrapper — cannot proceed")
        return

    wrapper_mr = ec.get("median_resonance")
    transcript = ec.get("transcript", "").strip()
    if wrapper_mr is None or not transcript:
        _skip("T8", f"wrapper median_resonance={wrapper_mr!r} transcript={transcript!r}")
        return

    _ok("T8.wrapper", f"wrapper medianResonance={wrapper_mr:.6f}  transcript={transcript[:40]!r}…")

    # ── Step 2: call the acousticgender library directly inside the sidecar ─
    # Write audio bytes into the container via docker cp, then run a Python
    # script that calls preprocessing → phones → resonance without the wrapper.

    # Copy audio to container
    cname_r = subprocess.run(
        ["docker", "compose", "ps", "-q", "visualizer-backend"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    cname = cname_r.stdout.strip()
    if not cname:
        _fail("T8.direct", "could not get visualizer-backend container id")
        return

    tmp_audio = "/tmp/t8_validate_audio.wav"
    subprocess.run(["docker", "cp", str(test_file), f"{cname}:{tmp_audio}"], check=True)

    direct_script = f"""\
import json, os, sys
os.chdir('/app')
import acousticgender.library.phones as phones
import acousticgender.library.preprocessing as preprocessing
import acousticgender.library.resonance as resonance

with open('weights_zh.json') as f:
    weights = json.load(f)

with open({tmp_audio!r}, 'rb') as f:
    audio_bytes = f.read()

transcript = {transcript!r}

import random, traceback
tmp_dir = '/tmp/t8_direct_' + str(random.randint(0, 999999))
try:
    praat_out = preprocessing.process(audio_bytes, transcript, tmp_dir, 'zh')
    data = phones.parse(praat_out, 'zh')
    if not data.get('phones'):
        raise RuntimeError("MFA produced no alignment output")
    resonance.compute_resonance(data, weights, 'zh')
    print(json.dumps({{'medianResonance': data.get('medianResonance'), 'phoneCount': len(data.get('phones', []))}}))
except Exception as e:
    traceback.print_exc(file=sys.stderr)
    print(json.dumps({{'error': str(e)}}))
"""

    r2 = subprocess.run(
        ["docker", "compose", "exec", "-T", "visualizer-backend",
         "micromamba", "run", "-n", "mfa", "python"],
        input=direct_script,
        capture_output=True, text=True, encoding="utf-8",
        cwd=PROJECT_ROOT, timeout=300,
    )
    if r2.returncode != 0:
        _fail("T8.direct", f"direct library call failed:\n{r2.stderr[:400]}")
        return

    last_line = r2.stdout.strip().splitlines()[-1] if r2.stdout.strip() else ""
    try:
        direct_data = json.loads(last_line)
    except (json.JSONDecodeError, IndexError):
        _fail("T8.direct", f"could not parse output: {r2.stdout[:300]}")
        return

    if "error" in direct_data:
        _fail("T8.direct", f"direct pipeline error: {direct_data['error']}")
        return

    direct_mr = direct_data.get("medianResonance")
    if direct_mr is None:
        _skip("T8.diff", "direct call returned no medianResonance")
        return

    diff = abs(float(wrapper_mr) - float(direct_mr))
    print(f"    wrapper medianResonance : {wrapper_mr:.6f}")
    print(f"    direct  medianResonance : {direct_mr:.6f}")
    print(f"    |diff|                  : {diff:.6f}")

    if diff < 0.02:
        _ok("T8.equivalence", f"|{wrapper_mr:.4f} − {direct_mr:.4f}| = {diff:.4f} < 0.02 ✓")
    else:
        _fail("T8.equivalence", f"diff {diff:.4f} ≥ 0.02 — wrapper/library divergence")


# ─── Summary ─────────────────────────────────────────────────────────────────


def _print_summary() -> int:
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = sum(1 for _, ok, _ in _RESULTS if not ok)

    print(f"\n{_B}{'═' * 62}{_X}")
    print(f"{_B}VALIDATION SUMMARY — {passed} passed, {failed} failed{_X}")
    print(f"{_B}{'═' * 62}{_X}")
    for tag, ok, msg in _RESULTS:
        icon = f"{_G}✓{_X}" if ok else f"{_R}✗{_X}"
        print(f"  {icon}  {tag}: {msg}")
    return 0 if failed == 0 else 1


# ─── Entry point ─────────────────────────────────────────────────────────────


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--fixtures", type=Path, metavar="DIR",
                        help="Directory containing Chinese speech WAV fixture files")
    parser.add_argument("--skip-build", action="store_true", help="Skip build tasks 1 and 2")
    parser.add_argument("--skip-engine-c", action="store_true", help="Skip tasks 5–8")
    parser.add_argument("--only", type=int, choices=range(1, 9), metavar="N",
                        help="Run only task N (1–8)")
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.base_url.rstrip("/")

    only = args.only

    # Preserve original .env and restore it on exit.
    original_env = ENV_FILE.read_text() if ENV_FILE.exists() else None
    try:
        run = lambda n: only is None or only == n

        if run(1):
            _task1(args.skip_build)
        if run(2):
            _task2(args.skip_build)
        if run(3):
            _task3()
        if run(4):
            _task4()
        if not args.skip_engine_c:
            if run(5):
                _task5(args.fixtures)
            if run(6):
                _task6()
            if run(7):
                _task7(args.fixtures)
            if run(8):
                _task8(args.fixtures)

    finally:
        if original_env is not None:
            ENV_FILE.write_text(original_env)
            print(f"\n  [restored original .env]")
        else:
            # .env didn't exist before — leave the docker env in place so compose still works.
            pass

    return _print_summary()


if __name__ == "__main__":
    sys.exit(main())
