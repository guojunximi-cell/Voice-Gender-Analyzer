from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    app_name: str = "Voice Gender Analyzer"
    admin_email: str = "fanhenna@outlook.com"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"] = "WARNING"
    web_dir: Path = BASE_DIR.parent / "web"

    # ─── 安全配置 ──────────────────────────────────────────────────
    max_file_size_mb: int = 10
    max_audio_duration_sec: int = 3 * 60
    rate_limit_ct: int = 10
    rate_limit_duration_sec: int = 60

    # ─── 并发控制 ──────────────────────────────────────────────────
    max_concurrent: int = 2
    max_queue_depth: int = 10


CFG: Settings


def load_config():
    global CFG
    CFG = Settings()
