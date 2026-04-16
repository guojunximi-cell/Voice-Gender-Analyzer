"""一键启动三端（后端 / TaskIQ worker / 前端），调试友好版本。

设计要点
────────
* **不藏日志**：三个子进程全部走「继承父进程 stdio」的方式，uvicorn/taskiq/vite
  的彩色原生输出直接打到当前终端。不再经 `subprocess.PIPE` + 读行线程，否则
  会吞掉 tqdm 回车、颜色、交互式提示。
* **三端同生共死**：任一子进程退出就把其余全部收掉；Ctrl+C 一次性干净退出。
* **worker 必须在这里起**：之前 `run_app.py` 只起了 backend + frontend，遇到
  `taskiq worker` 要用户另开终端手动跑。只要 worker 掉线或用的 redis 配置
  不对齐，API 端 `kiq()` 投递出去的任务就没人消费，SSE 轮询 30s 后会抛出
  "task not found" 类的 404 —— 先把 worker 纳入同一个启动链路，后续定位才
  能看到实时 worker 日志。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
WEB_DIR = BASE_DIR / "web"
# 注意用 127.0.0.1 而非 localhost：Windows Chrome 下 localhost 常优先解析到
# ::1，WSL 的端口转发只桥 IPv4，并且 Windows 侧 IPv6 的 5173 常被 Hyper-V /
# 代理 / 安全软件抢占，表现就是浏览器收到假 404。
VITE_URL = "http://127.0.0.1:5173"
BACKEND_PORT = int(os.environ.get("BACKEND_DEV_PORT", "8080"))


def _check_port_free(port: int) -> None:
    """提前探一下 127.0.0.1:<port> 是不是空的。

    上一次跑崩但子进程没收干净时，uvicorn 启动日志会是 "address already in use"，
    这条消息容易被淹没在一堆 tensorflow/absl warning 里。这里提前 bind 试探，
    占用就直接给出 PID 线索，省得翻日志。
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        hint = ""
        if os.name != "nt":
            # `ss -ltnp` 需要自己的端口归自己才能看到 PID；这里不保证一定有输出
            try:
                out = subprocess.check_output(
                    ("ss", "-ltnp", f"sport = :{port}"), text=True, stderr=subprocess.DEVNULL
                )
                hint = "\n" + out.strip()
            except Exception:
                pass
        print(
            f"❌ 端口 127.0.0.1:{port} 已被占用；通常是上次 backend 没退干净。{hint}\n"
            f"   处理：`lsof -i :{port}` / `fuser -k {port}/tcp` 后重试。"
        )
        sys.exit(1)
    finally:
        s.close()


# ── 环境准备 ────────────────────────────────────────────────────────────────

def _pick_python() -> str:
    """选一个能 import 到项目依赖的解释器。

    顺序：
    1. 当前解释器（通常已经是 `uv run python run_app.py` 或者 venv 里的）；
    2. 项目内 `.venv`；
    3. 没有就跑一次 `uv sync` 建出来。
    """
    in_venv = hasattr(sys, "real_prefix") or sys.base_prefix != sys.prefix
    if in_venv:
        return sys.executable

    venv = BASE_DIR / ".venv"
    if not venv.exists():
        print("📦 未检测到虚拟环境，执行 `uv sync`…")
        subprocess.run(("uv", "sync"), check=True, cwd=BASE_DIR)

    # Windows 放在 Scripts/，POSIX 在 bin/
    candidate = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(candidate) if candidate.exists() else sys.executable


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    # 保证子进程日志不被 Python 自身缓冲卡住（尤其 worker 里各种 print/logging）
    env["PYTHONUNBUFFERED"] = "1"
    # Windows 控制台打 Emoji 需要 UTF-8，否则 uvicorn 启动就崩
    env["PYTHONIOENCODING"] = "utf-8"
    # 让 uvicorn / vite 即使被 Popen 也保留颜色；终端本身支持时才生效
    env.setdefault("FORCE_COLOR", "1")
    env.setdefault("CLICOLOR_FORCE", "1")
    return env


# ── 子进程管理 ──────────────────────────────────────────────────────────────

class ProcGroup:
    """一个极简的子进程集合，负责启动、同生共死、信号转发。"""

    def __init__(self, env: dict[str, str]):
        self.env = env
        self.procs: list[tuple[str, subprocess.Popen]] = []
        self._stopping = False

        # Windows 下想给子进程发 CTRL_BREAK_EVENT，必须先把它放进独立进程组。
        # POSIX 下 os.setsid 能让我们后续 killpg 整组，避免残留 uvicorn reload 子进程。
        self._popen_extra: dict = {}
        if os.name == "nt":
            self._popen_extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            self._popen_extra["start_new_session"] = True

    def spawn(self, name: str, args: tuple[str, ...], cwd: Path | None = None) -> None:
        print(f"▶️  启动 [{name}]: {' '.join(args)}")
        p = subprocess.Popen(
            args,
            cwd=str(cwd or BASE_DIR),
            env=self.env,
            # 关键：stdout/stderr 留空 => 继承父进程终端 => 原生彩色日志
            **self._popen_extra,
        )
        self.procs.append((name, p))

    def shutdown(self, *_ignored) -> None:
        """收掉所有子进程；重复调用是幂等的。"""
        if self._stopping:
            return
        self._stopping = True
        print("\n🛑 正在关闭全部子进程…")

        for name, p in self.procs:
            if p.poll() is not None:
                continue
            try:
                if os.name == "nt":
                    # 对独立进程组发 Ctrl+Break，等价用户在那个子终端按了 Ctrl+C
                    p.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    # killpg 能把 uvicorn 的 reload 子进程、vite 的 esbuild 子进程一并带走
                    os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as e:
                print(f"  ⚠️ 通知 [{name}] 退出失败: {e}")

        # 给各家 8s 做 graceful shutdown；超时再 kill。
        deadline = time.time() + 8
        for name, p in self.procs:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                print(f"  ⏱  [{name}] 未在 8s 内退出，强制 kill")
                try:
                    if os.name == "nt":
                        p.kill()
                    else:
                        os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        sys.exit(0)

    def watch(self) -> None:
        """阻塞到任一子进程退出，然后拉齐收尾。"""
        while True:
            for name, p in self.procs:
                rc = p.poll()
                if rc is not None:
                    print(f"❌ [{name}] 已退出 (code={rc})，关闭其余子进程")
                    self.shutdown()
            time.sleep(0.5)


# ── 主流程 ─────────────────────────────────────────────────────────────────

def main() -> None:
    py = _pick_python()
    env = _build_env()
    npm_cmd = os.environ.get("NPM_CMD", "pnpm")

    print(f"📂 项目根目录: {BASE_DIR}")
    print(f"🐍 Python: {py}")
    print(f"📦 前端包管理器: {npm_cmd}")

    if not (WEB_DIR / "node_modules").exists():
        print(f"⚠️  前端依赖缺失，先执行 `{npm_cmd} install`…")
        subprocess.run((npm_cmd, "install"), check=True, cwd=WEB_DIR)

    _check_port_free(BACKEND_PORT)

    group = ProcGroup(env)

    # 1) FastAPI / uvicorn —— voiceya/__main__.py 固定监听 127.0.0.1:8080
    group.spawn("backend", (py, "-m", "voiceya"))

    # 2) TaskIQ worker —— 这是之前漏掉的一环。
    #    显式把含 @broker.task 的模块列在参数里，让 worker 在导入 broker 的同时
    #    注册任务；否则 receiver 能跑，但 task map 是空的，kiq 过来的消息会被
    #    当成未知任务 ack 掉，最终表现就是 API 那边一直等不到事件。
    group.spawn(
        "worker",
        (
            py, "-m", "taskiq", "worker",
            "voiceya.taskiq:broker",
            "voiceya.tasks.analyser",
            "--workers", "1",   # 单 worker 够用；多的话要注意 GPU/模型重复加载
            "--log-level", "INFO",
        ),
    )

    # 3) Vite —— 走 pnpm/npm，具体命令在 web/package.json 的 dev 脚本里
    group.spawn("frontend", (npm_cmd, "run", "dev"), cwd=WEB_DIR)

    # 信号：Ctrl+C / kill 都走同一套收尾逻辑
    signal.signal(signal.SIGINT, group.shutdown)
    signal.signal(signal.SIGTERM, group.shutdown)
    if os.name != "nt":
        signal.signal(signal.SIGHUP, group.shutdown)

    # 等 vite 起来再弹浏览器；首次启动慢一点，这里给足 4 秒
    time.sleep(4)
    print(f"🌐 打开浏览器: {VITE_URL}")
    try:
        webbrowser.open(VITE_URL)
    except Exception as e:
        print(f"  ⚠️ 无法自动打开浏览器: {e}")

    print("\n✅ 三端已全部启动，按 Ctrl+C 退出。\n")
    try:
        group.watch()
    except KeyboardInterrupt:
        group.shutdown()


if __name__ == "__main__":
    main()
