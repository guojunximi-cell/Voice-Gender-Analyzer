import asyncio
import os
import tempfile
import time
import numpy as np

# numpy 2.x made np.stack() reject generators; patch it early so librosa/
# inaSpeechSegmenter code that passes generator expressions still works.
_orig_np_stack = np.stack
def _np_stack_compat(arrays, *args, **kwargs):
    if not isinstance(arrays, (list, tuple)):
        arrays = list(arrays)
    return _orig_np_stack(arrays, *args, **kwargs)
np.stack = _np_stack_compat

import librosa
from collections import defaultdict
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List
import uvicorn

from inaSpeechSegmenter import Segmenter
from acoustic_analyzer import analyze_segment

# ─── 并发控制 ──────────────────────────────────────────────────
# 同时最多处理的请求数（超出时排队等待，而非拒绝）
MAX_CONCURRENT  = int(os.environ.get("MAX_CONCURRENT", "2"))
# 排队等待的上限（超出时才返回 503）
MAX_QUEUE_DEPTH = int(os.environ.get("MAX_QUEUE_DEPTH", "10"))

_processing_sem = asyncio.Semaphore(MAX_CONCURRENT)
_queue_depth    = 0
_queue_lock     = asyncio.Lock()

# ─── 安全配置 ──────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_MB", "5")) * 1024 * 1024

# IP 速率限制：滑动窗口计数器
RATE_LIMIT_MAX_CALLS = int(os.environ.get("RATE_LIMIT_MAX_CALLS", "10"))
RATE_LIMIT_WINDOW_SEC = int(os.environ.get("RATE_LIMIT_WINDOW_SEC", "60"))

_ip_call_times: dict = defaultdict(list)
_ip_rate_lock = asyncio.Lock()

# 允许的文件扩展名白名单（第一道防线）
_ALLOWED_EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.opus', '.m4a', '.aac', '.aiff', '.au', '.caf'}


def _is_valid_audio_magic(data: bytes) -> bool:
    """通过 magic bytes 校验上传内容是否为真实音频文件（防止伪装扩展名攻击）"""
    if len(data) < 12:
        return False
    # WAV:  RIFF????WAVE
    if data[0:4] == b'RIFF' and data[8:12] == b'WAVE':
        return True
    # FLAC
    if data[0:4] == b'fLaC':
        return True
    # OGG (Vorbis / Opus)
    if data[0:4] == b'OggS':
        return True
    # MP3 with ID3 tag
    if data[0:3] == b'ID3':
        return True
    # MP3 MPEG sync word (0xFF E2–FF)
    if data[0] == 0xFF and data[1] in (0xFB, 0xFA, 0xF3, 0xF2, 0xF1, 0xE3, 0xE2):
        return True
    # AIFF / AIFF-C:  FORM????AIFF|AIFC
    if data[0:4] == b'FORM' and data[8:12] in (b'AIFF', b'AIFC'):
        return True
    # M4A / AAC / MP4 audio:  ????ftyp
    if data[4:8] == b'ftyp':
        return True
    # CAF (Core Audio Format)
    if data[0:4] == b'caff':
        return True
    # AU / SND
    if data[0:4] == b'.snd':
        return True
    return False


async def _check_rate_limit(ip: str) -> None:
    """滑动窗口速率限制；超限时抛出 429"""
    async with _ip_rate_lock:
        now = time.monotonic()
        cutoff = now - RATE_LIMIT_WINDOW_SEC
        # 清理窗口期外的旧记录
        _ip_call_times[ip] = [t for t in _ip_call_times[ip] if t > cutoff]
        if len(_ip_call_times[ip]) >= RATE_LIMIT_MAX_CALLS:
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁：每 {RATE_LIMIT_WINDOW_SEC} 秒最多允许 {RATE_LIMIT_MAX_CALLS} 次请求，请稍后再试"
            )
        _ip_call_times[ip].append(now)

seg = None

@asynccontextmanager
async def lifespan(_app: FastAPI):
    global seg
    print("🚀 正在将 AI 模型载入内存...")
    try:
        loop = asyncio.get_event_loop()
        seg = await loop.run_in_executor(None, lambda: Segmenter(detect_gender=True))
        print("✅ Engine A (inaSpeechSegmenter) 加载完毕")
    except Exception as e:
        print(f"❌ Engine A 加载失败: {e}")
        seg = None
    yield

# 1. FastAPI 实例
app = FastAPI(title="VFP Voice Analysis API", version="2.0", lifespan=lifespan)

# 2. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. 静态文件（Vite 构建产物）
_DIST_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST_DIR, "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(os.path.join(_DIST_DIR, "index.html"))
else:
    @app.get("/")
    def root():
        return {"status": "ok", "name": "VFP Voice Analysis API", "version": "2.0", "docs": "/docs"}


# ─── 配置接口 ──────────────────────────────────────────────────
@app.get("/api/config")
def get_config():
    return {"max_concurrent": MAX_CONCURRENT, "max_queue_depth": MAX_QUEUE_DEPTH}


# ─── 核心接口 ──────────────────────────────────────────────────
@app.post("/api/analyze-voice")
async def analyze_voice(request: Request, files: List[UploadFile] = File(...)):
    global _queue_depth

    # ── 1. IP 速率限制 ─────────────────────────────────────────
    client_ip = request.client.host
    await _check_rate_limit(client_ip)

    # ── 2. 文件安全校验 ────────────────────────────────────────
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"不支持的文件类型 '{ext}'，仅接受: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            )

        header = await f.read(12)
        if not _is_valid_audio_magic(header):
            raise HTTPException(
                status_code=415,
                detail=f"文件 '{f.filename}' 的内容与声称的格式不符，拒绝处理"
            )

        # 文件大小限制（多读 1 字节判断是否超限，避免大文件载入内存）
        rest = await f.read(MAX_FILE_SIZE_BYTES - 12 + 1)
        if len(header) + len(rest) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件 '{f.filename}' 超过 {MAX_FILE_SIZE_BYTES // (1024*1024)} MB 大小限制"
            )

        await f.seek(0)

    # ── 3. 队列控制：超出最大等待数时拒绝，否则排队 ──────────
    async with _queue_lock:
        if _queue_depth >= MAX_QUEUE_DEPTH:
            raise HTTPException(
                status_code=503,
                detail=f"服务器繁忙，当前排队已达上限 ({MAX_QUEUE_DEPTH})，请稍后再试"
            )
        _queue_depth += 1

    try:
        # 获取信号量 → 同时最多 MAX_CONCURRENT 个请求在处理
        async with _processing_sem:
            results = await asyncio.gather(*[_do_analyze(f) for f in files])
    finally:
        async with _queue_lock:
            _queue_depth -= 1

    return results if len(results) > 1 else results[0]



async def _do_analyze(file: UploadFile):
    print(f"📥 收到文件: {file.filename}")

    file_ext = os.path.splitext(file.filename)[1].lower() or ".wav"

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        # ── Engine A: 时间分段 ─────────────────────────────────
        if seg is None:
            raise RuntimeError("Engine A (inaSpeechSegmenter) 未能成功加载，无法分析")
        print("⚙️  Engine A 分析中...")
        loop = asyncio.get_running_loop()
        segmentation_result = await loop.run_in_executor(None, seg, tmp_path)
        # segmentation_result: [('male'|'female'|..., start, end), ...]

        analysis_data    = []
        total_female_sec = 0.0
        total_male_sec   = 0.0
        voiced_acoustics = []   # [(acoustics_dict, duration_sec), ...]

        for seg_item in segmentation_result:
            label = seg_item[0]
            start_time = seg_item[1]
            end_time = seg_item[2]
            ina_confidence = seg_item[3] if len(seg_item) > 3 else None
            duration = end_time - start_time
            acoustics = None

            # ── Engine B: 声学分析（仅对有声语音段）────────────
            if label in ("female", "male") and duration >= 0.5:
                try:
                    # librosa.load 直接支持时间偏移切片，无需 pydub
                    y_seg, _ = librosa.load(
                        tmp_path,
                        sr=22050,
                        mono=True,
                        offset=float(start_time),
                        duration=float(duration),
                    )
                    acoustics = analyze_segment(y_seg, 22050)
                    if acoustics:
                        voiced_acoustics.append((acoustics, duration))
                except Exception as e:
                    print(f"⚠️  Engine B 跳过 [{start_time:.1f}–{end_time:.1f}s]: {e}")

            # 置信度：直接使用 Engine A (inaSpeechSegmenter) 的逐帧均值概率
            confidence = round(float(ina_confidence), 4) if ina_confidence is not None else None

            analysis_data.append({
                "label":      label,
                "confidence": confidence,
                "start_time": round(float(start_time), 2),
                "end_time":   round(float(end_time),   2),
                "duration":   round(float(duration),   2),
                "acoustics":  acoustics,
            })

            if label == "female":
                total_female_sec += duration
            elif label == "male":
                total_male_sec += duration

        # ── 全局汇总统计 ───────────────────────────────────────
        total_voice_sec  = total_female_sec + total_male_sec
        female_ratio     = (total_female_sec / total_voice_sec) if total_voice_sec > 0 else 0.0

        overall_f0             = None
        overall_gender_score   = None

        if voiced_acoustics:
            # F0: 按时长加权均值
            f0_pairs = [
                (a["f0_median_hz"], d)
                for a, d in voiced_acoustics
                if a.get("f0_median_hz") is not None
            ]
            if f0_pairs:
                total_w = sum(d for _, d in f0_pairs)
                overall_f0 = int(round(sum(f * d for f, d in f0_pairs) / total_w))

            # Gender score: 按 voiced_frames 加权均值
            gs_pairs = [
                (a["gender_score"], a.get("voiced_frames", 1))
                for a, _ in voiced_acoustics
                if a.get("gender_score") is not None
            ]
            if gs_pairs:
                total_w = sum(w for _, w in gs_pairs)
                overall_gender_score = round(sum(s * w for s, w in gs_pairs) / total_w, 1)

        # Overall Engine A confidence: weighted mean by duration for voiced segments
        conf_pairs = [
            (item["confidence"], item["duration"])
            for item in analysis_data
            if item["confidence"] is not None and item["label"] in ("female", "male")
        ]
        overall_confidence = None
        if conf_pairs:
            total_w = sum(d for _, d in conf_pairs)
            if total_w > 0:
                overall_confidence = round(sum(c * d for c, d in conf_pairs) / total_w, 4)

        print(f"✅ 分析完成 — {len(analysis_data)} 段，"
              f"F0={overall_f0} Hz，性别评分={overall_gender_score}，"
              f"女性占比={female_ratio*100:.1f}%")

        return {
            "status":   "success",
            "filename": file.filename,
            "summary": {
                "total_female_time_sec":  round(total_female_sec, 2),
                "total_male_time_sec":    round(total_male_sec,   2),
                "female_ratio":           round(female_ratio, 4),
                "overall_f0_median_hz":   overall_f0,
                "overall_gender_score":   overall_gender_score,
                "overall_confidence":     overall_confidence,
                "dominant_label":         ("female" if female_ratio >= 0.5 else "male") if total_voice_sec > 0 else None,
            },
            "analysis": analysis_data,
        }

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        return {"status": "error", "message": str(e)}

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
