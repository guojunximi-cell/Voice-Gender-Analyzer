"""容器启动脚本：在同一个容器里跑 uvicorn + taskiq worker。

精简自 run_app.py 的 ProcGroup 模式，去掉 vite / 浏览器，适配 Railway 单容器多进程：
* 任一子进程退出都整体退出，让 Railway 重启策略接管
* SIGTERM/SIGINT 转发给两个子进程，超时后 SIGKILL
* stdio 继承父进程，uvicorn/taskiq 日志直接打到 Railway 日志面板
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

PORT = os.environ.get("PORT", "8080")

CHILDREN: list[tuple[str, subprocess.Popen]] = []
_STOPPING = False


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("FORCE_COLOR", "1")
    return env


def _spawn(name: str, args: tuple[str, ...], env: dict[str, str]) -> None:
    print(f"[start] launching {name}: {' '.join(args)}", flush=True)
    p = subprocess.Popen(args, env=env, start_new_session=True)
    CHILDREN.append((name, p))


def _shutdown(signum: int = signal.SIGTERM, _frame=None) -> None:
    global _STOPPING
    if _STOPPING:
        return
    _STOPPING = True

    print(f"[start] shutting down (signal={signum})", flush=True)
    for name, p in CHILDREN:
        if p.poll() is not None:
            continue
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            print(f"[start] failed to signal {name}: {e}", flush=True)

    deadline = time.time() + 10
    for name, p in CHILDREN:
        try:
            p.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            print(f"[start] {name} didn't exit in 10s, killing", flush=True)
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main() -> int:
    env = _build_env()

    _spawn(
        "api",
        (
            sys.executable,
            "-m",
            "uvicorn",
            "voiceya:app",
            "--host",
            "0.0.0.0",
            "--port",
            PORT,
            "--proxy-headers",
            "--forwarded-allow-ips",
            "*",
        ),
        env,
    )
    # 旧部署（Railway）切到 VPS 后开 REDIRECT_TO，所有请求 308 短路在中间件里，
    # 永远到不了 taskiq；worker 跑起来只会因为 Redis 不可达拖垮整个容器。
    if os.environ.get("REDIRECT_TO"):
        print("[start] REDIRECT_TO set — skipping worker (redirect-only mode)", flush=True)
    else:
        _spawn(
            "worker",
            (
                sys.executable,
                "-m",
                "taskiq",
                "worker",
                "voiceya.taskiq:broker",
                "voiceya.tasks.analyser",
                "--workers",
                "1",
                "--log-level",
                "INFO",
            ),
            env,
        )

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    exit_code = 0
    while True:
        time.sleep(0.5)
        for name, p in CHILDREN:
            rc = p.poll()
            if rc is None:
                continue
            print(f"[start] {name} exited (code={rc}), tearing down", flush=True)
            exit_code = rc if rc != 0 else 1
            _shutdown()
            return exit_code


if __name__ == "__main__":
    sys.exit(main())
