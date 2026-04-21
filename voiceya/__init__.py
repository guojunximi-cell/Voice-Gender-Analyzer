import sys

from voiceya.config import BASE_DIR, load_config
from voiceya.utils.patch_ina import patch_ina_submodule
from voiceya.utils.patch_numpy import patch_numpy

sys.path.append(str(BASE_DIR / "inaSpeechSegmenter"))
load_config()
patch_numpy()
patch_ina_submodule(BASE_DIR / "inaSpeechSegmenter" / "inaSpeechSegmenter")

# --- entry point ---
from voiceya.main import app  # noqa: E402

__all__ = ["app"]
