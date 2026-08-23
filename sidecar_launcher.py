"""Sidecar 入口 — 启动 FastAPI 后端服务。

被 PyInstaller 打包为单一可执行文件，供 Tauri 桌面壳作为 sidecar 启动。
"""

import os
import sys
import threading

import uvicorn

import backend.app  # noqa: F401  让 PyInstaller 静态分析收集完整依赖（含 fastapi/sqlite3 等）


def _watch_stdin_and_exit() -> None:
    """宿主应用退出时自动终止。

    Tauri 壳通过管道把 stdin 接到 sidecar，主程序退出/崩溃时管道写端关闭，
    stdin 读取返回 EOF，随即结束整个进程（含 PyInstaller 子进程），
    避免后端残留占用 18989 端口。
    """
    try:
        # 该线程是 daemon，阻塞等待 Tauri 管道 EOF 不会阻止主线程退出；
        # 管道关闭时才终止 sidecar，避免父进程崩溃后残留端口占用。
        sys.stdin.read()
    except Exception:
        pass
    finally:
        # sidecar 的 Python 进程由 Tauri 管理，使用 os._exit 跳过解释器清理，
        # 确保 uvicorn 及其子线程不会在宿主已退出后继续存活。
        os._exit(0)


if __name__ == "__main__":
    threading.Thread(target=_watch_stdin_and_exit, daemon=True).start()
    uvicorn.run(
        "backend.app:app",
        host="127.0.0.1",
        port=18989,
        log_level="info",
    )
