# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# NOTE: Engine B (acoustic_analyzer) 已于 2026-04-07 永久下线并完全移除。
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'inaSpeechSegmenter-interspeech23'))
import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
import numpy as np

# numpy 2.x made np.stack/vstack/hstack reject generators; patch them early
# so librosa/pyannote/inaSpeechSegmenter code that passes generator
# expressions still works.  Root cause: pyannote viterbi.py calls
# np.vstack(generator_expr) at lines 86 and 95.
_orig_np_stack  = np.stack
_orig_np_vstack = np.vstack
_orig_np_hstack = np.hstack

def _np_stack_compat(arrays, *args, **kwargs):
    if not isinstance(arrays, (list, tuple)):
        arrays = list(arrays)
    return _orig_np_stack(arrays, *args, **kwargs)

def _np_vstack_compat(tup, *args, **kwargs):
    if not isinstance(tup, (list, tuple)):
        tup = list(tup)
    return _orig_np_vstack(tup, *args, **kwargs)

def _np_hstack_compat(tup, *args, **kwargs):
    if not isinstance(tup, (list, tuple)):
        tup = list(tup)
    return _orig_np_hstack(tup, *args, **kwargs)

np.stack  = _np_stack_compat
np.vstack = _np_vstack_compat
np.hstack = _np_hstack_compat

import librosa
from collections import defaultdict
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import List
import uvicorn

from inaSpeechSegmenter import Segmenter

# ─── 声学特征提取 ──────────────────────────────────────────────
MIN_ACOUSTICS_DUR = 0.5  # 短于此时长（秒）的片段不提取声学特征


def _value_to_tier(value, thresholds):
    """将标量映射到 1–5 级（给定 4 个升序阈值）。value 为 None 时返回 None。"""
    if value is None:
        return None
    for i, t in enumerate(thresholds):
        if value < t:
            return i + 1
    return 5


def _extract_acoustics(y_full: np.ndarray, sr: int, start: float, end: float):
    """提取单个有声片段的声学特征（F0、共振峰、级别分类）。
    片段过短或提取失败时返回 None。
    """
    if (end - start) < MIN_ACOUSTICS_DUR:
        return None
    y = y_full[int(start * sr):int(end * sr)]
    if len(y) < int(MIN_ACOUSTICS_DUR * sr):
        return None
    result = {}

    # ── F0（基频）：使用 pyin 算法 ────────────────────────────
    try:
        f0, voiced_flag, _ = librosa.pyin(y, fmin=65.0, fmax=500.0, sr=sr)
        voiced_f0 = f0[voiced_flag & ~np.isnan(f0)]
        if len(voiced_f0) > 0:
            result['f0_median_hz'] = round(float(np.median(voiced_f0)), 1)
            result['f0_std_hz']    = round(float(np.std(voiced_f0)), 1) if len(voiced_f0) > 1 else 0.0
        else:
            result['f0_median_hz'] = result['f0_std_hz'] = None
    except Exception:
        result['f0_median_hz'] = result['f0_std_hz'] = None

    # ── 共振峰：LPC 法估计 F1/F2/F3 ──────────────────────────
    try:
        y_pre = librosa.effects.preemphasis(y)
        order = int(2 + sr / 1000)          # ≈ 24 @ 22050 Hz
        a     = librosa.lpc(y_pre, order=order)
        roots = np.roots(a)
        roots = roots[np.imag(roots) >= 0]
        freqs = np.sort(np.angle(roots) * (sr / (2 * np.pi)))
        fmts  = freqs[(freqs > 300) & (freqs < 4000)]
        result['f1_hz'] = round(float(fmts[0])) if len(fmts) > 0 else None
        result['f2_hz'] = round(float(fmts[1])) if len(fmts) > 1 else None
        result['f3_hz'] = round(float(fmts[2])) if len(fmts) > 2 else None
    except Exception:
        result['f1_hz'] = result['f2_hz'] = result['f3_hz'] = None

    # ── 级别分类（与 metrics-panel.js SUB_SCORE_DEFS 一致）───
    result['pitch_tier']   = _value_to_tier(result['f0_median_hz'], [120, 155, 185, 225])
    result['formant_tier'] = _value_to_tier(result.get('f2_hz'),    [1400, 1600, 1900, 2200])
    return result


# ─── 日志配置 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("vfp")


class _MaskIPFilter(logging.Filter):
    """将 uvicorn 访问日志中的客户端 IP 替换为脱敏格式（保留前两段，后两段替换为 *）"""
    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "client_addr"):
            addr: str = record.client_addr          # e.g. "192.168.1.100:54321"
            host, _, port = addr.rpartition(":")
            parts = host.split(".")
            if len(parts) == 4:
                record.client_addr = f"{parts[0]}.{parts[1]}.*.*:{port}"
        return True

# ─── 并发控制 ──────────────────────────────────────────────────
# 同时最多处理的请求数（超出时排队等待，而非拒绝）
MAX_CONCURRENT  = int(os.environ.get("MAX_CONCURRENT", "2"))
# 排队等待的上限（超出时才返回 503）
MAX_QUEUE_DEPTH = int(os.environ.get("MAX_QUEUE_DEPTH", "10"))

_processing_sem = asyncio.Semaphore(MAX_CONCURRENT)
_queue_depth    = 0
_queue_lock     = asyncio.Lock()

# ─── 安全配置 ──────────────────────────────────────────────────
MAX_FILE_SIZE_MB    = int(os.environ.get("MAX_FILE_SIZE_MB", "10"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

MAX_AUDIO_DURATION_SEC = int(os.environ.get("MAX_AUDIO_DURATION_SEC", "180"))  # 最多 3 分钟

# IP 速率限制：滑动窗口计数器
RATE_LIMIT_MAX_CALLS = int(os.environ.get("RATE_LIMIT_MAX_CALLS", "10"))
RATE_LIMIT_WINDOW_SEC = int(os.environ.get("RATE_LIMIT_WINDOW_SEC", "60"))

_ip_call_times: dict = defaultdict(list)
_ip_rate_locks: dict = defaultdict(asyncio.Lock)  # 每个 IP 独立锁，避免全局串行化

# 允许的文件扩展名白名单（第一道防线）
_ALLOWED_EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.opus', '.m4a', '.aac', '.aiff', '.au', '.caf', '.webm'}


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
    # WebM / Matroska (EBML header)
    if data[0:4] == b'\x1a\x45\xdf\xa3':
        return True
    return False


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _transcode_to_mp3(in_path: str, out_path: str) -> None:
    """将任意音频格式转码为 64kbps 单声道 22050Hz MP3，减少分析时的 I/O 开销。"""
    subprocess.run(
        [
            'ffmpeg', '-y',
            '-i', in_path,
            '-ar', '22050',  # 与 librosa.load sr=22050 一致，避免二次重采样
            '-ac', '1',      # 单声道，分析引擎仅使用单声道
            '-b:a', '64k',   # 64kbps CBR，人声分析完全够用
            '-f', 'mp3',
            out_path,
        ],
        
        check=True,
        timeout=120,
        capture_output=True,
    )


async def _check_rate_limit(ip: str) -> None:
    """滑动窗口速率限制；超限时抛出 429"""
    async with _ip_rate_locks[ip]:
        now = time.monotonic()
        cutoff = now - RATE_LIMIT_WINDOW_SEC
        # 清理窗口期外的旧记录
        recent = [t for t in _ip_call_times[ip] if t > cutoff]
        if not recent:
            _ip_call_times.pop(ip, None)
            recent = []
        else:
            _ip_call_times[ip] = recent
        if len(recent) >= RATE_LIMIT_MAX_CALLS:
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁：每 {RATE_LIMIT_WINDOW_SEC} 秒最多允许 {RATE_LIMIT_MAX_CALLS} 次请求，请稍后再试"
            )
        _ip_call_times[ip].append(now)

seg = None

@asynccontextmanager
async def lifespan(_app: FastAPI):
    global seg
    # 在 lifespan 最早期挂载 IP 脱敏过滤器，确保覆盖所有访问日志
    logging.getLogger("uvicorn.access").addFilter(_MaskIPFilter())
    logger.info("正在将 AI 模型载入内存...")
    try:
        loop = asyncio.get_event_loop()
        seg = await loop.run_in_executor(None, lambda: Segmenter(detect_gender=True))
        logger.info("Engine A (inaSpeechSegmenter) 加载完毕")
        # ── logit 模型诊断 ──
        if seg is not None and hasattr(seg, 'gender'):
            _g = seg.gender
            _last3 = [(type(l).__name__, getattr(l, 'name', '?')) for l in _g.nn.layers[-3:]]
            logger.info("[Gender诊断] 最后3层: %s", _last3)
            logger.info("[Gender诊断] logit_model=%s  pen_model=%s  dense_W=%s",
                        getattr(_g, '_logit_model', 'MISSING') is not None,
                        getattr(_g, '_pen_model', 'MISSING') is not None,
                        getattr(_g, '_dense_W', None).shape if getattr(_g, '_dense_W', None) is not None else None)
    except Exception as e:
        logger.error("Engine A 加载失败: %s", e)
        seg = None
    yield

# 1. FastAPI 实例
app = FastAPI(title="VFP Voice Analysis API", version="2.0", lifespan=lifespan)

# 2. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
    return {
        "max_concurrent": MAX_CONCURRENT,
        "max_queue_depth": MAX_QUEUE_DEPTH,
        "allow_concurrent": MAX_CONCURRENT > 1,
        "max_file_size_mb": MAX_FILE_SIZE_MB,
        "max_audio_duration_sec": MAX_AUDIO_DURATION_SEC,
    }


# ─── 核心接口 ──────────────────────────────────────────────────
@app.post("/api/analyze-voice")
async def analyze_voice(request: Request, files: List[UploadFile] = File(...)):
    global _queue_depth

    # ── 1. IP 速率限制 ─────────────────────────────────────────
    # 优先从 X-Forwarded-For 获取真实 IP（反向代理场景），回退到 request.client
    _forwarded = request.headers.get("x-forwarded-for")
    if _forwarded:
        client_ip = _forwarded.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host
    else:
        client_ip = "unknown"
    await _check_rate_limit(client_ip)

    # ── 2. 文件安全校验 ────────────────────────────────────────
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"上传的文件格式不受支持，仅接受: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            )

        header = await f.read(12)
        if not _is_valid_audio_magic(header):
            raise HTTPException(
                status_code=415,
                detail="文件内容与声称的格式不符，请检查文件是否为有效音频"
            )

        # 文件大小限制（多读 1 字节判断是否超限，避免大文件载入内存）
        rest = await f.read(MAX_FILE_SIZE_BYTES - 12 + 1)
        if len(header) + len(rest) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"上传的音频文件超过 {MAX_FILE_SIZE_BYTES // (1024*1024)} MB 大小限制"
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

    # ── 4. SSE 流式响应（单文件 + Accept: text/event-stream）──
    wants_stream = (
        len(files) == 1
        and "text/event-stream" in request.headers.get("accept", "")
    )

    if wants_stream:
        # Read file content eagerly here — UploadFile's SpooledTemporaryFile
        # may be closed after this function returns, before the lazy streaming
        # generator gets a chance to call file.read(), causing "read of closed file".
        _stream_content = await files[0].read()
        _stream_filename = files[0].filename or "upload"

        async def _guarded_stream():
            """Hold semaphore & queue slot for the full streaming lifetime."""
            global _queue_depth
            try:
                async with _processing_sem:
                    async for chunk in _do_analyze_stream(_stream_filename, _stream_content):
                        yield chunk
            finally:
                async with _queue_lock:
                    _queue_depth -= 1

        return StreamingResponse(
            _guarded_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── 5. 经典 JSON 响应（批量 / 不支持 SSE 的客户端）────────
    try:
        # 获取信号量 → 同时最多 MAX_CONCURRENT 个请求在处理
        async with _processing_sem:
            results = await asyncio.gather(*[_do_analyze(f) for f in files])
    finally:
        async with _queue_lock:
            _queue_depth -= 1

    return results if len(results) > 1 else results[0]



async def _do_analyze_stream(filename: str, content: bytes):
    """Async generator: yields SSE event strings with real progress, last event has type='result'."""
    task_id = uuid.uuid4().hex[:8]
    logger.info("收到文件 [Task: %s] (大小待测量)", task_id)

    file_ext = os.path.splitext(filename)[1].lower() or ".wav"

    tmp_path = None
    mp3_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            tmp_path = tmp.name   # 在写入之前赋值，确保 finally 能清理
            tmp.write(content)
        # ── 转码：统一为 64kbps 单声道 MP3，降低后续 I/O 开销 ──
        yield _sse_event({"type": "progress", "pct": 5, "msg": "鸭鸭正在处理音频…"})
        loop = asyncio.get_running_loop()
        mp3_path = tmp_path + '_normalized.mp3'
        try:
            await loop.run_in_executor(None, _transcode_to_mp3, tmp_path, mp3_path)
            analysis_path = mp3_path
            logger.info("已转码为标准化 MP3 [Task: %s]", task_id)
        except Exception as e:
            logger.warning("ffmpeg 转码失败，回退至原始文件 [Task: %s]: %s", task_id, e)
            analysis_path = tmp_path

        # ── 时长限制 ───────────────────────────────────────────
        yield _sse_event({"type": "progress", "pct": 8, "msg": "鸭鸭在检查音频时长…"})
        try:
            audio_duration = await loop.run_in_executor(
                None, lambda: librosa.get_duration(path=analysis_path)
            )
            if audio_duration > MAX_AUDIO_DURATION_SEC:
                raise HTTPException(
                    status_code=413,
                    detail=f"音频时长 {audio_duration:.0f} 秒，超过 {MAX_AUDIO_DURATION_SEC} 秒（{MAX_AUDIO_DURATION_SEC // 60} 分钟）限制"
                )
            logger.info("音频时长 %.1f 秒 [Task: %s]", audio_duration, task_id)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("无法获取音频时长 [Task: %s]: %s", task_id, e)

        # ── Engine A: 时间分段 ─────────────────────────────────
        if seg is None:
            raise RuntimeError("Engine A (inaSpeechSegmenter) 未能成功加载，无法分析")
        yield _sse_event({"type": "progress", "pct": 10, "msg": "鸭鸭正在聆听声纹…（此步骤较慢）"})
        logger.info("Engine A 分析中... [Task: %s]", task_id)
        # 用 keepalive ping 防止 Railway 代理因长时间无数据而关闭 SSE 连接
        _seg_fut = loop.run_in_executor(None, seg, analysis_path)
        while not _seg_fut.done():
            try:
                await asyncio.wait_for(asyncio.shield(_seg_fut), timeout=15)
            except asyncio.TimeoutError:
                yield _sse_event({"type": "progress", "pct": 10, "msg": "鸭鸭正在聆听声纹…（此步骤较慢）"})
        segmentation_result = await _seg_fut
        # segmentation_result: [('male'|'female'|..., start, end), ...]

        yield _sse_event({"type": "progress", "pct": 50, "msg": "鸭鸭听完了！正在提取声学特征…"})

        # ── 加载音频（一次性），供声学特征提取使用 ────────────
        y_full, sr_full = None, 22050
        try:
            y_full, sr_full = await loop.run_in_executor(
                None, lambda: librosa.load(analysis_path, sr=22050, mono=True)
            )
            logger.info("librosa 加载完毕 [Task: %s]", task_id)
        except Exception as e:
            logger.warning("librosa.load 失败，跳过声学特征 [Task: %s]: %s", task_id, e)

        analysis_data    = []
        total_female_sec = 0.0
        total_male_sec   = 0.0

        for seg_item in segmentation_result:
            label = seg_item[0]
            start_time = seg_item[1]
            end_time = seg_item[2]
            ina_confidence = seg_item[3] if len(seg_item) > 3 else None
            confidence_frames = seg_item[4] if len(seg_item) > 4 else None
            duration = end_time - start_time

            # 置信度：直接使用 Engine A (inaSpeechSegmenter) 的逐帧均值概率
            confidence = round(float(ina_confidence), 4) if ina_confidence is not None else None

            # 声学特征（仅有声片段）
            acoustics = None
            if y_full is not None and label in ('male', 'female'):
                try:
                    acoustics = await loop.run_in_executor(
                        None, _extract_acoustics, y_full, sr_full, start_time, end_time
                    )
                except Exception as e:
                    logger.warning("声学特征提取失败 [Task: %s]: %s", task_id, e)

            analysis_data.append({
                "label":      label,
                "confidence": confidence,
                "confidence_frames": confidence_frames,
                "start_time": round(float(start_time), 2),
                "end_time":   round(float(end_time),   2),
                "duration":   round(float(duration),   2),
                "acoustics":  acoustics,
            })

            if label == "female":
                total_female_sec += duration
            elif label == "male":
                total_male_sec += duration

        yield _sse_event({"type": "progress", "pct": 90, "msg": "声学特征提取完毕，正在整理…"})

        # ── 全局汇总统计 ───────────────────────────────────────
        yield _sse_event({"type": "progress", "pct": 98, "msg": "鸭鸭快好了…"})
        total_voice_sec  = total_female_sec + total_male_sec
        female_ratio     = (total_female_sec / total_voice_sec) if total_voice_sec > 0 else 0.0

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

        logger.info(
            "分析完成 [Task: %s] — %d 段，女性占比=%.1f%%",
            task_id, len(analysis_data), female_ratio * 100,
        )

        result = {
            "status":   "success",
            "filename": filename,
            "summary": {
                "total_female_time_sec":  round(total_female_sec, 2),
                "total_male_time_sec":    round(total_male_sec,   2),
                "female_ratio":           round(female_ratio, 4),
                "overall_confidence":     overall_confidence,
                "dominant_label":         ("female" if female_ratio >= 0.5 else "male") if total_voice_sec > 0 else None,
            },
            "analysis": analysis_data,
        }
        yield _sse_event({"type": "result", "pct": 100, "data": result})

    except HTTPException as e:
        logger.error("分析失败 [Task: %s]: %s", task_id, e.detail)
        yield _sse_event({"type": "error", "msg": e.detail})
    except Exception as e:
        logger.error("分析失败 [Task: %s]: %s", task_id, e)
        yield _sse_event({"type": "error", "msg": str(e)})

    finally:
        for p in (tmp_path, mp3_path):
            if p and os.path.exists(p):
                os.remove(p)


async def _do_analyze(file: UploadFile):
    """Non-streaming wrapper: consumes the stream generator, returns the final result."""
    content = await file.read()
    filename = file.filename or "upload"
    last_result = None
    async for event_str in _do_analyze_stream(filename, content):
        line = event_str.strip()
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            if payload.get("type") == "result":
                last_result = payload["data"]
            elif payload.get("type") == "error":
                return {"status": "error", "message": payload["msg"]}
    return last_result or {"status": "error", "message": "未收到分析结果"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
