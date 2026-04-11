import os
import runpy
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def stream_output(pipe, prefix):
    """在独立线程中读取输出，防止阻塞"""
    try:
        if pipe:
            for line in iter(pipe.readline, ""):
                print(f"[{prefix}] {line.strip()}")
    except Exception:
        pass


def run_app():
    # 1. 获取项目根目录（基于当前脚本位置）
    # 使用 Path 对象处理路径更现代、更安全
    base_dir = Path(__file__).parent
    frontend_dir = base_dir / "web"

    print(f"📂 项目根目录: {base_dir}")

    # 2. 确定 Python 解释器路径
    # 优先检测当前环境是否已经是虚拟环境，或者寻找本地 venv
    python_executable = sys.executable

    # 如果当前不是虚拟环境，尝试寻找项目下的 venv
    is_venv = hasattr(sys, "real_prefix") or (sys.base_prefix != sys.prefix)
    if not is_venv:
        for path in base_dir.iterdir():
            if path.name not in {"venv", ".venv", "env"}:
                continue

            venv_path = path
            break

        else:
            subprocess.run(("uv", "sync"))
            venv_path = base_dir / ".venv"

        runpy.run_path(str(venv_path / "scripts/activate_this.py"))
        python_executable = sys.executable

    print(f"🐍 使用 Python: {python_executable}")

    # 3. 检查前端环境
    npm_cmd = os.environ.get("NPM_CMD", "pnpm")
    if not (frontend_dir / "node_modules").exists():
        print("⚠️ 警告: 找不到前端 node_modules，尝试在 web 目录下运行 'pnpm install'")

    print("🚀 正在启动 VGAv2 项目...")

    # 4. 启动后端
    print("📡 正在启动后端 (FastAPI)...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"  # 强制使用 UTF-8，解决 Windows 下的 Emoji 打印崩溃问题

    backend_process = subprocess.Popen(
        (python_executable, "-m", "backend"),
        cwd=str(base_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # 5. 启动前端
    print("🎨 正在启动前端 (Vite)...")
    frontend_process = subprocess.Popen(
        (npm_cmd, "run", "dev"),
        cwd=str(frontend_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # 启动输出监控线程
    threading.Thread(
        target=stream_output, args=(backend_process.stdout, "后端"), daemon=True
    ).start()
    threading.Thread(
        target=stream_output, args=(frontend_process.stdout, "前端"), daemon=True
    ).start()

    def cleanup(signum, frame):
        print("\n🛑 正在关闭所有服务...")
        try:
            backend_process.terminate()
            frontend_process.terminate()
        except:
            pass
        sys.exit(0)

    # 注册退出信号
    if sys.platform != "win32":
        signal.signal(signal.SIGHUP, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # 等待前端启动并打开浏览器
    time.sleep(4)
    web_url = "http://localhost:5173"
    print(f"🌐 正在打开浏览器: {web_url}")
    webbrowser.open(web_url)

    print("\n✅ 服务运行中！按 Ctrl+C 退出。")

    # 保持主进程运行
    try:
        while True:
            if backend_process.poll() is not None:
                print("❌ 后端进程已意外停止。")
                break
            if frontend_process.poll() is not None:
                print("❌ 前端进程已意外停止。")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup(None, None)


if __name__ == "__main__":
    run_app()
