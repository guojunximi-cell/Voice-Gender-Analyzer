import sys
from pathlib import Path


def init_iss_module(proj_root: Path):
    sys.path.append(str(proj_root / "voiceya/inaSpeechSegmenter"))

    from inaSpeechSegmenter import Segmenter

    Segmenter(detect_gender=True)


if __name__ == "__main__":
    DIR = Path(__file__).parents[1]
    init_iss_module(DIR)
