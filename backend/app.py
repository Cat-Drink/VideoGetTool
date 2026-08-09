"""FastAPI sidecar 服务入口。

将现有 Python 爬虫/下载/数据库能力暴露为 REST API + WebSocket，
供 Tauri 前端调用。使用 lifespan 管理启动/关闭生命周期。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

# 确保项目根目录在 sys.path 中，以便 import app/ crawlers/ downloader/
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config, database
from app.logger import get_logger, setup_logger
from backend.api import config as config_router
from backend.api import cookie as cookie_router
from backend.api import crawler as crawler_router
from backend.api import download as download_router
from backend.api import health as health_router
from backend.api import ws as ws_router
from backend.state import ctx


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI 生命周期：启动时初始化，关闭时清理。"""
    log = get_logger(__name__)
    log.info("=== 撷风拾影 Python Sidecar 启动 ===")

    # 1. 日志与目录
    setup_logger()
    config.ensure_app_dirs()

    # 2. 数据库初始化
    ctx.conn = database.init_default_db()
    log.info("数据库已初始化: %s", config.DB_PATH)

    # 3. Repository 层
    from app.repositories import (
        ConfigRepository,
        CookieRepository,
        MetadataRepository,
        TaskItemRepository,
        TaskRepository,
    )

    ctx.task_repo = TaskRepository(ctx.conn)
    ctx.task_item_repo = TaskItemRepository(ctx.conn)
    ctx.cookie_repo = CookieRepository(ctx.conn)
    ctx.config_repo = ConfigRepository(ctx.conn)
    ctx.metadata_repo = MetadataRepository(ctx.conn)

    # 4. 爬虫层组件
    from crawlers.cookie_tester import CookieTester
    from crawlers.http_client import HttpClient
    from crawlers.signer import Signer
    from crawlers.url_parser import URLParser
    from crawlers.user_home_crawler import UserHomeCrawler
    from crawlers.video_parser import VideoParser

    ctx.signer = Signer()
    ctx.http_client = HttpClient(ctx.cookie_repo, ctx.signer)
    ctx.url_parser = URLParser(ctx.http_client)
    ctx.video_parser = VideoParser(ctx.http_client, ctx.signer)
    ctx.user_home_crawler = UserHomeCrawler(ctx.http_client, ctx.signer)
    ctx.cookie_tester = CookieTester(ctx.http_client, ctx.signer)

    # 5. 下载调度器
    from downloader.scheduler import Scheduler

    def _on_item_completed(task_item_id: int) -> None:
        """下载完成回调：记录日志并触发 WebSocket 广播。"""
        log.info("任务项 %d 下载完成", task_item_id)
        try:
            asyncio.create_task(
                ws_router.manager.broadcast(
                    {
                        "type": "item_completed",
                        "task_item_id": task_item_id,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            )
        except Exception:
            log.exception("广播 item_completed 消息失败")

    def _on_item_failed(task_item_id: int, fail_reason: str) -> None:
        """下载失败回调：记录日志并触发 WebSocket 广播。"""
        log.warning("任务项 %d 下载失败: %s", task_item_id, fail_reason)
        try:
            asyncio.create_task(
                ws_router.manager.broadcast(
                    {
                        "type": "item_failed",
                        "task_item_id": task_item_id,
                        "fail_reason": fail_reason,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            )
        except Exception:
            log.exception("广播 item_failed 消息失败")

    def _on_progress(updates: list) -> None:
        """进度回调：通过 WebSocket 广播进度更新。"""
        if not updates:
            return
        try:
            asyncio.create_task(
                ws_router.manager.broadcast(
                    {
                        "type": "progress",
                        "updates": [
                            {
                                "task_item_id": update.task_item_id,
                                "downloaded_bytes": update.downloaded_bytes,
                                "total_bytes": update.total_bytes,
                                "progress": (
                                    100.0
                                    if update.status == "completed"
                                    else round(
                                        (update.downloaded_bytes / max(update.total_bytes, 1))
                                        * 100,
                                        1,
                                    )
                                ),
                                "status": update.status,
                            }
                            for update in updates
                        ],
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            )
        except Exception:
            log.exception("广播进度消息失败")

    ctx.scheduler = Scheduler(
        conn=ctx.conn,
        http_client=None,
        on_item_completed=_on_item_completed,
        on_item_failed=_on_item_failed,
        on_progress=_on_progress,
        video_parser=ctx.video_parser,
        cookie_repository=ctx.cookie_repo,
    )

    # 6. 启动调度器
    await ctx.scheduler.start()
    await ctx.scheduler.restore_pending_tasks()
    log.info("调度器已启动，断点续传已恢复")

    yield  # FastAPI 开始处理请求

    # 关闭阶段
    log.info("=== 关闭清理 ===")
    await ctx.scheduler.stop()
    with contextlib.suppress(Exception):
        ctx.conn.close()
    for task in ctx._bg_tasks:
        task.cancel()
    log.info("=== Python Sidecar 已关闭 ===")


# ===== FastAPI 应用 =====
app = FastAPI(
    title="撷风拾影 Python Sidecar",
    version="0.3.2",
    lifespan=lifespan,
)

# CORS：允许 Tauri 前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health_router.router, prefix="/api", tags=["health"])
app.include_router(download_router.router, prefix="/api/download", tags=["download"])
app.include_router(crawler_router.router, prefix="/api/crawler", tags=["crawler"])
app.include_router(cookie_router.router, prefix="/api/cookie", tags=["cookie"])
app.include_router(config_router.router, prefix="/api/config", tags=["config"])
app.include_router(ws_router.router, prefix="/api", tags=["ws"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="127.0.0.1", port=18989, reload=True)
