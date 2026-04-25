"""Engine A load-time microbenchmark.

每个阶段在独立子进程里跑，避免 import 缓存污染。打印 JSON 到 stdout。

Usage:
    .venv/bin/python scripts/bench_engine_a_load.py [--runs N]

阶段（每阶段一个独立子进程）：
  - import_keras       : `import keras` cold time
  - segmenter_init     : 加载 SMN + Gender 两个 HDF5
  - first_predict      : 第一次 nn.predict 触发 graph trace
  - second_predict     : 第二次 nn.predict 稳态延迟（基准）

最后聚合 N 次，输出 min/median/mean/max。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv" / "bin" / "python"

ENV_TWEAKS = {
    "TF_CPP_MIN_LOG_LEVEL": "3",
    "CUDA_VISIBLE_DEVICES": "",
    "TF_FORCE_GPU_ALLOW_GROWTH": "false",
}

# 用 subprocess 跑这些 snippet，每段最后 print(json.dumps({"ms": ...}))。
SNIPPETS = {
    "import_keras": r"""
import json, time
t0 = time.perf_counter()
import keras  # noqa: F401
print(json.dumps({"ms": (time.perf_counter() - t0) * 1000}))
""",
    "segmenter_init": r"""
import json, sys, time
from pathlib import Path
sys.path.append(str(Path("voiceya/inaSpeechSegmenter")))
# 与 voiceya 包同样的 patch（不导入 voiceya 以免触发 load_config）
from voiceya.utils.patch_ina import patch_ina_submodule
patch_ina_submodule(Path("voiceya/inaSpeechSegmenter/inaSpeechSegmenter"))
from voiceya.utils.patch_numpy import patch_numpy
patch_numpy()

from inaSpeechSegmenter.segmenter import Segmenter

t0 = time.perf_counter()
seg = Segmenter(detect_gender=True, ffmpeg=None)
print(json.dumps({"ms": (time.perf_counter() - t0) * 1000}))
""",
    "first_second_predict": r"""
import json, sys, time
from pathlib import Path
sys.path.append(str(Path("voiceya/inaSpeechSegmenter")))
from voiceya.utils.patch_ina import patch_ina_submodule
patch_ina_submodule(Path("voiceya/inaSpeechSegmenter/inaSpeechSegmenter"))
from voiceya.utils.patch_numpy import patch_numpy
patch_numpy()

import numpy as np
from inaSpeechSegmenter.segmenter import Segmenter

seg = Segmenter(detect_gender=True, ffmpeg=None)

# 21 维 mspec 给 SMN，24 维给 Gender；都是 (1, 68, n_mel, 1) 的 patch
vad_in = np.zeros((1, 68, 21, 1), dtype="float32")
gen_in = np.zeros((1, 68, 24, 1), dtype="float32")

t0 = time.perf_counter()
seg.vad.nn.predict(vad_in, batch_size=32, verbose=0)
seg.gender.nn.predict(gen_in, batch_size=32, verbose=0)
first_ms = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
seg.vad.nn.predict(vad_in, batch_size=32, verbose=0)
seg.gender.nn.predict(gen_in, batch_size=32, verbose=0)
second_ms = (time.perf_counter() - t0) * 1000

print(json.dumps({"first_ms": first_ms, "second_ms": second_ms}))
""",
    "init_plus_warmup": r"""
# 模拟阶段 2：Segmenter.__init__ + warmup 假推理 一起跑，作为新 worker 启动总耗时
import json, sys, time
from pathlib import Path
sys.path.append(str(Path("voiceya/inaSpeechSegmenter")))
from voiceya.utils.patch_ina import patch_ina_submodule
patch_ina_submodule(Path("voiceya/inaSpeechSegmenter/inaSpeechSegmenter"))
from voiceya.utils.patch_numpy import patch_numpy
patch_numpy()

import numpy as np
from inaSpeechSegmenter.segmenter import Segmenter

t0 = time.perf_counter()
seg = Segmenter(detect_gender=True, ffmpeg=None)
init_ms = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
vad_in = np.zeros((1, 68, seg.vad.nmel, 1), dtype="float32")
seg.vad.nn.predict(vad_in, batch_size=seg.vad.batch_size, verbose=0)
gen_in = np.zeros((1, 68, seg.gender.nmel, 1), dtype="float32")
seg.gender.nn.predict(gen_in, batch_size=seg.gender.batch_size, verbose=0)
warmup_ms = (time.perf_counter() - t0) * 1000

# warmup 后真实"首请求"推理延迟（应该接近 baseline 的 second_predict）
t0 = time.perf_counter()
seg.vad.nn.predict(vad_in, batch_size=seg.vad.batch_size, verbose=0)
seg.gender.nn.predict(gen_in, batch_size=seg.gender.batch_size, verbose=0)
post_warmup_first_ms = (time.perf_counter() - t0) * 1000

print(json.dumps({
    "init_ms": init_ms,
    "warmup_ms": warmup_ms,
    "post_warmup_first_ms": post_warmup_first_ms,
}))
""",
    "init_plus_warmup_patched": r"""
# 模拟阶段 3：经过 voiceya 包入口（env setdefault + numpy patch + ina patch）+
# _patch_segmenter_for_frame_confidence（并行加载补丁）+ warmup。
# 即等价于真实 worker 启动 load_seg() 的全链路。
import json, time
import voiceya  # 触发 env setdefault / patch_numpy / patch_ina_submodule
from voiceya.services.audio_analyser.seg import _patch_segmenter_for_frame_confidence
_patch_segmenter_for_frame_confidence()

import numpy as np
from inaSpeechSegmenter.segmenter import Segmenter

t0 = time.perf_counter()
seg = Segmenter(detect_gender=True, ffmpeg=None)
init_ms = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
vad_in = np.zeros((1, 68, seg.vad.nmel, 1), dtype="float32")
seg.vad.nn.predict(vad_in, batch_size=seg.vad.batch_size, verbose=0)
gen_in = np.zeros((1, 68, seg.gender.nmel, 1), dtype="float32")
seg.gender.nn.predict(gen_in, batch_size=seg.gender.batch_size, verbose=0)
warmup_ms = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
seg.vad.nn.predict(vad_in, batch_size=seg.vad.batch_size, verbose=0)
seg.gender.nn.predict(gen_in, batch_size=seg.gender.batch_size, verbose=0)
post_warmup_first_ms = (time.perf_counter() - t0) * 1000

print(json.dumps({
    "init_ms": init_ms,
    "warmup_ms": warmup_ms,
    "post_warmup_first_ms": post_warmup_first_ms,
}))
""",
}


def run(snippet: str, env_tweaks: bool = False) -> dict:
    """跑一段 python，从 stdout 最后一行解析 JSON。"""
    env = os.environ.copy()
    if env_tweaks:
        env.update(ENV_TWEAKS)
    out = subprocess.run(
        [str(PY), "-c", snippet],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
        env=env,
    )
    if out.returncode != 0:
        sys.stderr.write(f"--- subprocess failed ---\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}\n")
        raise RuntimeError(f"subprocess exit {out.returncode}")

    # 最后一个非空行应该是 JSON
    lines = [ln for ln in out.stdout.strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


def stats(values: list[float]) -> dict:
    return {
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "mean": round(statistics.mean(values), 1),
        "max": round(max(values), 1),
        "n": len(values),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--label", type=str, default="baseline", help="标签写到结果里方便对比")
    ap.add_argument(
        "--env-tweaks",
        action="store_true",
        help="子进程注入 TF_CPP_MIN_LOG_LEVEL=3 / CUDA_VISIBLE_DEVICES='' / TF_FORCE_GPU_ALLOW_GROWTH=false",
    )
    ap.add_argument(
        "--with-warmup",
        action="store_true",
        help="测 init+warmup 模式（阶段 2 之后必开）",
    )
    ap.add_argument(
        "--patched",
        action="store_true",
        help="用 voiceya patch 后的 Segmenter（阶段 3 后必开）。隐含 --with-warmup 和 --env-tweaks。",
    )
    args = ap.parse_args()
    if args.patched:
        args.with_warmup = True
        args.env_tweaks = True

    results = {
        "label": args.label,
        "runs": args.runs,
        "import_keras_ms": [],
        "segmenter_init_ms": [],
        "first_predict_ms": [],
        "second_predict_ms": [],
        "init_ms": [],
        "warmup_ms": [],
        "post_warmup_first_ms": [],
    }

    for i in range(args.runs):
        sys.stderr.write(f"[{i + 1}/{args.runs}] import_keras...\n")
        r = run(SNIPPETS["import_keras"], env_tweaks=args.env_tweaks)
        results["import_keras_ms"].append(r["ms"])

        if args.with_warmup:
            snippet_key = "init_plus_warmup_patched" if args.patched else "init_plus_warmup"
            sys.stderr.write(f"[{i + 1}/{args.runs}] {snippet_key}...\n")
            r = run(SNIPPETS[snippet_key], env_tweaks=args.env_tweaks)
            results["init_ms"].append(r["init_ms"])
            results["warmup_ms"].append(r["warmup_ms"])
            results["post_warmup_first_ms"].append(r["post_warmup_first_ms"])
        else:
            sys.stderr.write(f"[{i + 1}/{args.runs}] segmenter_init...\n")
            r = run(SNIPPETS["segmenter_init"], env_tweaks=args.env_tweaks)
            results["segmenter_init_ms"].append(r["ms"])

            sys.stderr.write(f"[{i + 1}/{args.runs}] predict (1st + 2nd)...\n")
            r = run(SNIPPETS["first_second_predict"], env_tweaks=args.env_tweaks)
            results["first_predict_ms"].append(r["first_ms"])
            results["second_predict_ms"].append(r["second_ms"])

    summary: dict = {"label": args.label, "import_keras": stats(results["import_keras_ms"])}
    if args.with_warmup:
        summary["init"] = stats(results["init_ms"])
        summary["warmup"] = stats(results["warmup_ms"])
        summary["post_warmup_first_predict"] = stats(results["post_warmup_first_ms"])
        summary["cold_start_total"] = stats(
            [
                a + b + c
                for a, b, c in zip(
                    results["import_keras_ms"],
                    results["init_ms"],
                    results["warmup_ms"],
                    strict=True,
                )
            ]
        )
    else:
        summary["segmenter_init"] = stats(results["segmenter_init_ms"])
        summary["first_predict"] = stats(results["first_predict_ms"])
        summary["second_predict"] = stats(results["second_predict_ms"])
        summary["cold_start_total"] = stats(
            [
                a + b
                for a, b in zip(
                    results["import_keras_ms"], results["segmenter_init_ms"], strict=True
                )
            ]
        )

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
