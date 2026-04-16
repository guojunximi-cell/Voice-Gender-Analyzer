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


CFG: Settings = None  # type: ignore


def load_config():
    global CFG

    CFG = Settings()  # type: ignore
