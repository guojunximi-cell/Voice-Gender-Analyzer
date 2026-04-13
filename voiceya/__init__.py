import sys

from backend.config import BASE_DIR, load_config
from backend.utils.patch_numpy import patch_numpy

sys.path.append(str(BASE_DIR / "inaSpeechSegmenter"))
load_config()
patch_numpy()

# --- entry point ---
from main import app  # noqa: E402

__all__ = ["app"]
