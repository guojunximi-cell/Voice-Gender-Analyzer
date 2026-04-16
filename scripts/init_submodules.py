import os
import shutil
from pathlib import Path
from subprocess import PIPE, run


def apply_sparse_checkout_cfgs(proj_root: Path):
    for cfg_path in (proj_root / "scripts/sparse-checkout-cfgs").iterdir():
        if not cfg_path.is_file():
            return

        module = cfg_path.name.replace("%", "/")

        shutil.copyfile(cfg_path, proj_root / f".git/modules/{module}/info/sparse-checkout")

        os.chdir(proj_root / module)
        run(("git", "sparse-checkout", "init", "--no-cone"), stdout=PIPE)


def init_submodules(proj_root: Path):
    os.chdir(proj_root)

    run(("git", "submodule", "init"), stdout=PIPE)
    apply_sparse_checkout_cfgs(proj_root)


if __name__ == "__main__":
    DIR = Path(__file__).parents[1]
    init_submodules(DIR)
