import sys
from pathlib import Path


def init_iss_module(proj_root: Path):
    ina_root = proj_root / "voiceya/inaSpeechSegmenter"
    sys.path.append(str(ina_root))
    sys.path.append(str(proj_root))

    from voiceya.utils.patch_ina import patch_ina_submodule

    patch_ina_submodule(ina_root / "inaSpeechSegmenter")

    from inaSpeechSegmenter import Segmenter

    Segmenter(detect_gender=True)


if __name__ == "__main__":
    DIR = Path(__file__).parents[1]
    init_iss_module(DIR)
