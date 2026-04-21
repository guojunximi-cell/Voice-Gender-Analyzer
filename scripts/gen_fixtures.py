"""Generate Chinese speech fixture WAVs using Microsoft Edge TTS.

Outputs 13 files into tests/fixtures/audio/:
  female_1..5.wav  (zh-CN female neural voices)
  male_1..5.wav    (zh-CN male neural voices)
  zh_10s.wav       (female_1 truncated to 10 s)
  zh_30s.wav       (female_1 truncated to 30 s)
  zh_60s.wav       (female_1 truncated to 60 s)

Requirements:
  pip install edge-tts
  ffmpeg in PATH
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Text corpus — ~500-char Mandarin news passage, clear enunciation
# ---------------------------------------------------------------------------
TEXT = (
    "近年来，人工智能技术的迅猛发展深刻改变了人们的日常生活。"
    "从智能手机上的语音助手，到医院里辅助诊断的影像识别系统，"
    "再到工厂中精准操作的机械臂，人工智能的身影无处不在。"
    "科学家们正在研究如何让机器更好地理解自然语言，"
    "从而实现人与计算机之间更加流畅的沟通。"
    "与此同时，数据安全和隐私保护也成为社会各界关注的焦点。"
    "专家指出，技术的发展必须与完善的法律法规相配套，"
    "才能真正造福社会，避免潜在的风险与危害。"
    "未来，随着算力的持续提升和算法的不断优化，"
    "人工智能将在教育、医疗、交通等更多领域发挥重要作用。"
)

# ---------------------------------------------------------------------------
# Voice map
# ---------------------------------------------------------------------------
FEMALE_VOICES = [
    "zh-CN-XiaoxiaoNeural",   # female_1 — warm
    "zh-CN-XiaoyiNeural",     # female_2 — lively
    "zh-CN-liaoning-XiaobeiNeural",  # female_3 — dialect
    "zh-CN-shaanxi-XiaoniNeural",    # female_4 — dialect
    "zh-CN-XiaoyiNeural",     # female_5 — repeat (only 4 available)
]

MALE_VOICES = [
    "zh-CN-YunxiNeural",      # male_1 — lively
    "zh-CN-YunjianNeural",    # male_2 — passion (deep)
    "zh-CN-YunyangNeural",    # male_3 — professional
    "zh-CN-YunxiaNeural",     # male_4 — cute
    "zh-CN-YunjianNeural",    # male_5 — repeat (only 4 available)
]

OUT_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "audio"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def synthesize_mp3(text: str, voice: str, out_mp3: Path) -> None:
    """Call edge-tts and save raw MP3 output."""
    import edge_tts  # type: ignore[import]

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_mp3))


def mp3_to_wav(src: Path, dst: Path, sample_rate: int = 16000) -> None:
    """Convert MP3 → 16 kHz mono WAV via ffmpeg."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-sample_fmt",
            "s16",
            str(dst),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def truncate_wav(src: Path, dst: Path, duration_sec: float) -> None:
    """Truncate WAV to given duration via ffmpeg."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-t",
            str(duration_sec),
            "-c",
            "copy",
            str(dst),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wav_duration(path: Path) -> float:
    """Return WAV duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    entries: list[tuple[str, str, str]] = []
    for i, voice in enumerate(FEMALE_VOICES, start=1):
        entries.append((f"female_{i}", voice, "female"))
    for i, voice in enumerate(MALE_VOICES, start=1):
        entries.append((f"male_{i}", voice, "male"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        for name, voice, gender in entries:
            wav_path = OUT_DIR / f"{name}.wav"
            if wav_path.exists():
                dur = wav_duration(wav_path)
                print(f"  [skip] {name}.wav already exists ({dur:.1f}s)")
                continue

            print(f"  [tts]  {name}.wav  ({voice}) ...", end=" ", flush=True)
            mp3_path = tmp_path / f"{name}.mp3"
            await synthesize_mp3(TEXT, voice, mp3_path)
            mp3_to_wav(mp3_path, wav_path)
            dur = wav_duration(wav_path)
            print(f"done  {dur:.1f}s")

    # Derive duration-keyed files from female_1.wav
    src = OUT_DIR / "female_1.wav"
    src_dur = wav_duration(src)
    print(f"\n  source female_1.wav duration: {src_dur:.1f}s")

    for label, sec in [("zh_10s", 10), ("zh_30s", 30), ("zh_60s", 60)]:
        dst = OUT_DIR / f"{label}.wav"
        if dst.exists():
            dur = wav_duration(dst)
            print(f"  [skip] {label}.wav already exists ({dur:.1f}s)")
            continue
        if src_dur < sec:
            print(
                f"  [WARN] female_1.wav is only {src_dur:.1f}s, cannot make {label}.wav; using full clip"
            )
            truncate_wav(src, dst, src_dur)
        else:
            truncate_wav(src, dst, sec)
        actual = wav_duration(dst)
        print(f"  [clip] {label}.wav  {actual:.1f}s")

    print("\nAll fixtures ready:")
    for p in sorted(OUT_DIR.glob("*.wav")):
        dur = wav_duration(p)
        print(f"  {p.name:20s}  {dur:.1f}s")


if __name__ == "__main__":
    # Ensure UTF-8 output on Windows
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

    asyncio.run(main())
