import sys
from pathlib import Path


def _patch_ina_submodule(submodule_root: Path) -> None:
    # 与 voiceya.utils.patch_ina.patch_ina_submodule 同逻辑；这里内联是为了
    # 避免导入 voiceya 包触发 load_config()（Docker 构建时还没有 REDIS_URI）。
    for name in ("segmenter.py", "features_vbx.py", "vbx_segmenter.py", "thread_returning.py"):
        src = submodule_root / name
        if not src.exists():
            continue

        text = src.read_text()
        if text.startswith("from __future__ import annotations"):
            continue

        src.write_text("from __future__ import annotations\n" + text)


def init_iss_module(proj_root: Path):
    ina_root = proj_root / "voiceya/inaSpeechSegmenter"
    sys.path.append(str(ina_root))

    _patch_ina_submodule(ina_root / "inaSpeechSegmenter")

    from inaSpeechSegmenter import Segmenter

    Segmenter(detect_gender=True)


if __name__ == "__main__":
    DIR = Path(__file__).parents[1]
    init_iss_module(DIR)
