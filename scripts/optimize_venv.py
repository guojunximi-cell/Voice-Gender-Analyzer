import compileall
import os
import shutil
from pathlib import Path


def compile_venv(venv_root: Path):
    compileall.compile_dir(
        venv_root,
        quiet=1,
        optimize=[1, 2],  # type: ignore
        workers=(os.cpu_count() or 2) // 2,
        hardlink_dupes=True,
    )


def trim_venv(venv_root: Path):
    for path in venv_root.iterdir():
        if path.is_dir():
            if path.name.endswith(".dist-info"):
                shutil.rmtree(path)
                continue

            trim_venv(path)

        if not path.is_file():
            continue

        if (path.suffix in {".py", ".pyi", ".typed", ".pxd"}) or (
            path.suffix == ".pyc" and not path.name.endswith(".opt-2.pyc")
        ):
            path.unlink()


if __name__ == "__main__":
    DIR = Path(__file__).parents[1]
    VENV_DIR = DIR / ".venv"
    compile_venv(VENV_DIR)
    trim_venv(VENV_DIR)
