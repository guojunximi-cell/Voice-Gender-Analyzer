import os
import sys

# TF/Keras cold-import 调优：worker 镜像确定无 GPU，跳过 CUDA 库探测、抑制
# absl/oneDNN 日志格式化。必须在 import keras/tensorflow 之前 setdefault
# (Dockerfile stage 3 ENV 已显式设；这里兜底本地 dev)。
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("TF_FORCE_GPU_ALLOW_GROWTH", "false")

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
