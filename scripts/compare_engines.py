#!/usr/bin/env python3
"""Side-by-side Engine A / B / C comparison on a single audio file.

Read-only diagnostic tool -- does not modify any existing code or state.
Flags the pitch/resonance divergence scenario documented in EDGE-C
(docs/ENGINE_C_ROADMAP.md).

Usage
-----
  # Engine A + B only (default)
  python scripts/compare_engines.py path/to/audio.wav

  # Include Engine C (requires funasr + running sidecar)
  python scripts/compare_engines.py path/to/audio.wav --engine-c

  # Verbose per-segment breakdown
  python scripts/compare_engines.py path/to/audio.wav -v

Environment
-----------
Requires the full voiceya dev environment (TF/Keras, librosa, scipy, av).
Engine C additionally needs the ``engine-c`` dependency group and a running
visualizer-backend sidecar (see docker-compose.yml profile ``engine-c``).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from io import BytesIO
from pathlib import Path

# ── Bootstrap: make voiceya importable without starting the web server ──────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "voiceya" / "inaSpeechSegmenter"))

# Config requires REDIS_URL but this script never touches Redis.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from voiceya.config import load_config  # noqa: E402
from voiceya.utils.patch_numpy import patch_numpy  # noqa: E402

load_config()
patch_numpy()

import av  # noqa: E402
import librosa  # noqa: E402
import numpy as np  # noqa: E402
from av import AudioStream  # noqa: E402

from voiceya.config import CFG  # noqa: E402
from voiceya.services.audio_analyser.acoustic_analyzer import analyze_segment  # noqa: E402
from voiceya.services.audio_analyser.seg import load_seg, SEG  # noqa: E402
from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem  # noqa: E402
from voiceya.services.audio_analyser.statics import do_statics  # noqa: E402

# ── ANSI colours ────────────────────────────────────────────────────────────
_G = "\033[92m"
_R = "\033[91m"
_Y = "\033[93m"
_B = "\033[94m"
_D = "\033[2m"
_X = "\033[0m"

PITCH_RESONANCE_WARN_THRESHOLD = 30.0


# ── Audio helpers ───────────────────────────────────────────────────────────

def _transcode_to_pcm(path: str) -> BytesIO:
    """Transcode any audio file to 16 kHz mono PCM WAV (same as audio_tools)."""
    with av.open(path) as inp:
        i_stm = inp.streams.best("audio")
        assert isinstance(i_stm, AudioStream)
        i_stm.codec_context.thread_type = "AUTO"

        pcm = BytesIO()
        with av.open(pcm, "w", format="wav") as out:
            o_stm = out.add_stream("pcm_s16le", rate=16000)
            assert isinstance(o_stm, AudioStream)
            o_stm.codec_context.thread_type = "AUTO"
            o_stm.codec_context.layout = "mono"
            for frame in inp.decode(i_stm):
                for packet in o_stm.codec_context.encode_lazy(frame):
                    out.mux_one(packet)
            out.mux(o_stm.encode())

        pcm.seek(0)
        return pcm


def _get_duration(path: str) -> float:
    with av.open(path) as s:
        stm = s.streams.best("audio")
        assert isinstance(stm, AudioStream)
        if stm.duration is not None:
            return float(stm.duration * stm.time_base)
        if s.duration is not None:
            return s.duration / 1_000_000
        return 0.0


# ── Engine runners ──────────────────────────────────────────────────────────

async def _run_engine_a(pcm: BytesIO) -> list[tuple]:
    """Load segmenter and run Engine A, returning raw segmentation tuples."""
    await load_seg()
    pcm.seek(0)
    return await asyncio.to_thread(SEG, pcm)


def _run_engine_b(
    pcm: BytesIO,
    segmentation: list[tuple],
) -> list[AnalyseResultItem]:
    """Run Engine B acoustic analysis on every segment."""
    pcm.seek(0)
    y_full, sr = librosa.load(pcm, sr=None, mono=True)

    results: list[AnalyseResultItem] = []
    for seg_item in segmentation:
        r = AnalyseResultItem(
            label=seg_item[0],
            start_time=round(seg_item[1], 2),
            end_time=round(seg_item[2], 2),
            duration=round(seg_item[2] - seg_item[1], 2),
            confidence=round(seg_item[3], 4) if len(seg_item) > 3 else None,
            acoustics=None,
        )

        if r.label not in ("female", "male") or r.duration < 0.5:
            results.append(r)
            continue

        start = int(seg_item[1] * sr)
        end = int(seg_item[2] * sr)
        y_seg = y_full[start:end]
        if y_seg.size:
            r.acoustics = analyze_segment(y_seg, int(sr))

        results.append(r)
    return results


async def _run_engine_c(
    pcm: BytesIO,
    analyse_results: list[AnalyseResultItem],
) -> dict | None:
    """Run Engine C via the existing run_engine_c function."""
    from voiceya.services.audio_analyser.engine_c import run_engine_c

    pcm.seek(0)
    audio_bytes = pcm.read()
    return await run_engine_c(audio_bytes, analyse_results)


# ── Aggregation helpers ─────────────────────────────────────────────────────

def _aggregate_subscores(
    results: list[AnalyseResultItem],
) -> dict[str, float | None]:
    """Compute voiced-frame-weighted averages of Engine B subscores."""
    rows = []
    for r in results:
        a = r.acoustics
        if not a:
            continue
        rows.append((
            a["pitch_score"],
            a["formant_score"],
            a["resonance_score"],
            a["tilt_score"],
            a["voiced_frames"],
            a["f0_median_hz"],
            a.get("f1_hz"),
            a.get("f2_hz"),
            a.get("f3_hz"),
            a.get("vtl_cm"),
            a.get("h1_h2_db"),
        ))

    if not rows:
        return {k: None for k in (
            "pitch_score", "formant_score", "resonance_score", "tilt_score",
            "f0_median_hz", "f1_hz", "f2_hz", "f3_hz", "vtl_cm", "h1_h2_db",
        )}

    arr = np.array([(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows])
    w = arr[:, 4]  # voiced_frames as weights

    if not np.any(w):
        w = np.ones(len(rows))

    agg: dict[str, float | None] = {
        "pitch_score": float(np.average(arr[:, 0], weights=w)),
        "formant_score": float(np.average(arr[:, 1], weights=w)),
        "resonance_score": float(np.average(arr[:, 2], weights=w)),
        "tilt_score": float(np.average(arr[:, 3], weights=w)),
        "f0_median_hz": float(np.average(arr[:, 5], weights=w)),
    }

    # Median for formants/VTL/H1-H2 (not meaningful to weight-average)
    for idx, key in [(6, "f1_hz"), (7, "f2_hz"), (8, "f3_hz"),
                     (9, "vtl_cm"), (10, "h1_h2_db")]:
        vals = [r[idx] for r in rows if r[idx] is not None]
        agg[key] = float(np.median(vals)) if vals else None

    return agg


# ── Display ─────────────────────────────────────────────────────────────────

def _fmt(v, fmt=".1f", suffix="", na="--"):
    if v is None:
        return na
    return f"{v:{fmt}}{suffix}"


def _print_header(path: str, duration: float) -> None:
    name = Path(path).name
    print(f"\n{'=' * 66}")
    print(f"  Engine Comparison: {name}  ({duration:.1f} s)")
    print(f"{'=' * 66}")


def _print_engine_a(stats: dict) -> None:
    s = stats["summary"]
    analysis = stats["analysis"]

    n_female = sum(1 for r in analysis if r["label"] == "female")
    n_male = sum(1 for r in analysis if r["label"] == "male")
    n_other = sum(1 for r in analysis if r["label"] not in ("female", "male"))
    total_voiced = s["total_female_time_sec"] + s["total_male_time_sec"]

    print(f"\n{_B}--- Engine A (inaSpeechSegmenter) ---{_X}")
    print(f"  Segments:      {len(analysis)}  "
          f"({n_female} female, {n_male} male, {n_other} other)")
    print(f"  Voiced time:   {total_voiced:.1f} s  "
          f"(female {s['total_female_time_sec']:.1f} s / "
          f"male {s['total_male_time_sec']:.1f} s)")
    print(f"  Female ratio:  {s['female_ratio']:.4f}")
    print(f"  Dominant:      {s['dominant_label'] or '--'}")
    if s["overall_confidence"]:
        print(f"  Confidence:    {s['overall_confidence']:.4f}")


def _print_engine_b(stats: dict, agg: dict[str, float | None]) -> None:
    s = stats["summary"]

    print(f"\n{_B}--- Engine B (Acoustic Analysis) ---{_X}")

    if agg["pitch_score"] is None:
        print(f"  {_Y}No voiced segments with acoustic data.{_X}")
        return

    gs = s["overall_gender_score"]
    ps = agg["pitch_score"]
    fs = agg["formant_score"]
    rs = agg["resonance_score"]
    ts = agg["tilt_score"]

    # Determine if dynamic rebalancing kicks in
    rebalanced = abs(ps - fs) > 30
    w_p, w_f, w_r, w_t = (0.35, 0.35, 0.20, 0.10) if rebalanced else (0.45, 0.30, 0.15, 0.10)

    print(f"  Gender score:  {_fmt(gs)} / 100  (composite"
          f"{', rebalanced' if rebalanced else ''})")
    print(f"  |-- Pitch:     {ps:5.1f}   (weight {w_p:.0%})")
    print(f"  |-- Formant:   {fs:5.1f}   (weight {w_f:.0%})")
    print(f"  |-- Resonance: {rs:5.1f}   (weight {w_r:.0%})")
    print(f"  +-- Tilt:      {ts:5.1f}   (weight {w_t:.0%})")

    print()
    print(f"  F0 median:     {_fmt(agg['f0_median_hz'], '.0f', ' Hz')}")
    f1 = _fmt(agg["f1_hz"], ".0f")
    f2 = _fmt(agg["f2_hz"], ".0f")
    f3 = _fmt(agg["f3_hz"], ".0f")
    print(f"  Formants:      F1={f1}  F2={f2}  F3={f3} Hz")
    print(f"  VTL:           {_fmt(agg['vtl_cm'], '.1f', ' cm')}")
    print(f"  H1-H2:         {_fmt(agg['h1_h2_db'], '.1f', ' dB')}")

    # ── EDGE-C warning ──────────────────────────────────────────────────
    gap = abs(ps - rs)
    if gap > PITCH_RESONANCE_WARN_THRESHOLD:
        higher, lower = ("pitch", "resonance") if ps > rs else ("resonance", "pitch")
        print()
        print(f"  {_Y}!! WARNING: {higher}_score ({max(ps, rs):.1f}) vs "
              f"{lower}_score ({min(ps, rs):.1f}) gap = {gap:.1f}{_X}")
        print(f"  {_Y}   This exposes the composite-weight design flaw (EDGE-C).{_X}")
        if ps > rs:
            print(f"  {_Y}   Pitch training is ahead of resonance -- "
                  f"score is suppressed.{_X}")
        else:
            print(f"  {_Y}   Resonance reads feminine but pitch does not -- "
                  f"unusual pattern.{_X}")


def _print_engine_c(ec: dict | None, tried: bool) -> None:
    print(f"\n{_B}--- Engine C (FunASR + MFA + Praat) ---{_X}")

    if not tried:
        print(f"  {_D}Skipped (use --engine-c to enable){_X}")
        return

    if ec is None:
        print(f"  {_Y}Returned None (deps missing / sidecar down / "
              f"too little speech){_X}")
        return

    print(f"  Transcript:    {ec.get('transcript', '--')}")
    print(f"  Mean pitch:    {_fmt(ec.get('mean_pitch_hz'), '.1f', ' Hz')}")
    print(f"  Median res.:   {_fmt(ec.get('median_resonance'), '.4f')}")
    print(f"  Phone count:   {ec.get('phone_count', '--')}")
    print(f"  Word count:    {ec.get('word_count', '--')}")


def _print_segments(results: list[AnalyseResultItem]) -> None:
    """Verbose per-segment table."""
    print(f"\n{_B}--- Per-Segment Breakdown ---{_X}")
    print(f"  {'#':>3}  {'Label':<8} {'Start':>6} {'End':>6} "
          f"{'Dur':>5} {'F0':>5} {'Score':>6} "
          f"{'Pitch':>6} {'Fmnt':>6} {'Reson':>6} {'Tilt':>6} {'Warn':>4}")
    print(f"  {'---':>3}  {'-----':<8} {'-----':>6} {'-----':>6} "
          f"{'----':>5} {'---':>5} {'-----':>6} "
          f"{'-----':>6} {'----':>6} {'-----':>6} {'----':>6} {'----':>4}")

    for i, r in enumerate(results, 1):
        a = r.acoustics
        if a:
            ps = a["pitch_score"]
            rs = a["resonance_score"]
            gap = abs(ps - rs)
            warn = f"{_Y}!!{_X}" if gap > PITCH_RESONANCE_WARN_THRESHOLD else ""
            print(
                f"  {i:3d}  {r.label:<8} {r.start_time:6.2f} {r.end_time:6.2f} "
                f"{r.duration:5.2f} {a['f0_median_hz']:5.0f} {a['gender_score']:6.1f} "
                f"{ps:6.1f} {a['formant_score']:6.1f} {rs:6.1f} "
                f"{a['tilt_score']:6.1f} {warn:>4}"
            )
        else:
            print(
                f"  {i:3d}  {r.label:<8} {r.start_time:6.2f} {r.end_time:6.2f} "
                f"{r.duration:5.2f}   {'--':>3} {'--':>6} "
                f"{'--':>6} {'--':>6} {'--':>6} {'--':>6}"
            )


# ── Main ────────────────────────────────────────────────────────────────────

async def _run(args: argparse.Namespace) -> None:
    audio_path = args.audio
    if not Path(audio_path).is_file():
        print(f"Error: file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    duration = _get_duration(audio_path)
    _print_header(audio_path, duration)

    # ── Transcode ───────────────────────────────────────────────────────
    print(f"\n{_D}Transcoding to 16 kHz mono PCM...{_X}", end="", flush=True)
    pcm = _transcode_to_pcm(audio_path)
    print(f" {_G}done{_X} ({pcm.getbuffer().nbytes / 1024:.0f} KB)")

    # ── Engine A ────────────────────────────────────────────────────────
    print(f"{_D}Running Engine A (inaSpeechSegmenter)...{_X}", end="", flush=True)
    segmentation = await _run_engine_a(pcm)
    print(f" {_G}done{_X} ({len(segmentation)} segments)")

    # ── Engine B ────────────────────────────────────────────────────────
    print(f"{_D}Running Engine B (acoustic analysis)...{_X}", end="", flush=True)
    analyse_results = await asyncio.to_thread(_run_engine_b, pcm, segmentation)
    n_with_acoustics = sum(1 for r in analyse_results if r.acoustics)
    print(f" {_G}done{_X} ({n_with_acoustics} segments with acoustics)")

    # ── Statics ─────────────────────────────────────────────────────────
    stats = do_statics(analyse_results)
    agg = _aggregate_subscores(analyse_results)

    # ── Engine C (optional) ─────────────────────────────────────────────
    ec_result = None
    tried_c = args.engine_c
    if tried_c:
        print(f"{_D}Running Engine C (FunASR + sidecar)...{_X}", end="", flush=True)
        ec_result = await _run_engine_c(pcm, analyse_results)
        status = f"{_G}done{_X}" if ec_result else f"{_Y}skipped/failed{_X}"
        print(f" {status}")

    # ── Output ──────────────────────────────────────────────────────────
    _print_engine_a(stats)
    _print_engine_b(stats, agg)
    _print_engine_c(ec_result, tried_c)

    if args.verbose:
        _print_segments(analyse_results)

    print(f"\n{'=' * 66}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Side-by-side Engine A/B/C comparison on a single audio file.",
    )
    parser.add_argument("audio", help="Path to an audio file (wav, mp3, ogg, ...)")
    parser.add_argument("--engine-c", action="store_true",
                        help="Also run Engine C (needs funasr + running sidecar)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show per-segment breakdown table")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="[%(levelname)s] %(name)s - %(message)s",
    )

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
