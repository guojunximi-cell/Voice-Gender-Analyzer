from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, NonNegativeInt, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR.parent / ".env", env_file_encoding="utf-8")

    app_name: str = "Voice Gender Analyzer"
    admin_email: str = "fanhenna@outlook.com"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"] = "WARNING"

    redis_uri: str = Field(..., validation_alias=AliasChoices("REDIS_URI", "REDIS_URL"))
    web_dir: Path = BASE_DIR.parent / "web"

    task_max_exec_sec: PositiveInt = 15 * 60
    task_events_ttl_sec: PositiveInt = 10 * 60
    task_result_ttl_sec: PositiveInt = 10 * 60

    # ─── 安全配置 ──────────────────────────────────────────────────
    max_file_size_mb: PositiveInt = Field(10, le=512)
    max_audio_duration_sec: PositiveInt = 3 * 60
    rate_limit_ct: PositiveInt = 10
    rate_limit_duration_sec: PositiveInt = 60

    # ─── 并发控制 ──────────────────────────────────────────────────
    max_concurrent: PositiveInt = 2
    max_queue_depth: NonNegativeInt = 30

    # ─── Engine C / 进阶分析 ──────────────────────────────────────
    # feature-flagged，默认关；开启时需要 visualizer-backend sidecar 可达。
    engine_c_enabled: bool = False
    engine_c_sidecar_url: str = "http://visualizer-backend:8001"
    engine_c_sidecar_timeout_sec: PositiveInt = 60
    engine_c_min_duration_sec: PositiveInt = 3
    # Shared secret with the sidecar.  Empty string = unauthenticated (dev /
    # isolated docker network only).  When set, the worker sends the token
    # via X-Engine-C-Token; the sidecar (env ENGINE_C_TOKEN) requires a match.
    engine_c_sidecar_token: str = ""

    # ─── Engine C / 英文 ASR (faster-whisper) ────────────────────
    # 只有 free + en-US 模式会触达这些；script 模式或 zh 请求都不加载权重。
    # 模型 ID 取自 HuggingFace：tiny.en / base.en / small.en / medium.en.
    # device="auto" → 有 CUDA 用 CUDA，否则 CPU；compute_type int8 在 CPU 上平衡速度/体积。
    engine_c_whisper_model: str = "base.en"
    engine_c_whisper_device: str = "auto"
    engine_c_whisper_compute_type: str = "int8"

    # ─── Engine C / 法语 ASR (faster-whisper multilingual) ───────
    # 只有 free + fr-FR 模式触达；不能复用 *.en 检查点（英文专用）。
    # tiny / base / small / medium / large-v3 都可，base 在 CPU 上 ~2× 实时。
    engine_c_whisper_model_fr: str = "base"


CFG: Settings = None  # type: ignore


def load_config():
    global CFG

    CFG = Settings()  # type: ignore
