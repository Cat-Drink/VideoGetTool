"""应用上下文状态。

全局共享的单例实例，供 app.py 和各 API 路由模块导入。
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.repositories import (
        ConfigRepository,
        CookieRepository,
        MetadataRepository,
        TaskItemRepository,
        TaskRepository,
    )
    from crawlers.bilibili.bili_http_client import BiliHttpClient
    from crawlers.bilibili.bili_signer import BiliSigner
    from crawlers.bilibili.bili_url_parser import BiliURLParser
    from crawlers.bilibili.bili_user_crawler import BiliUserCrawler
    from crawlers.bilibili.bili_video_parser import BiliVideoParser
    from crawlers.cookie_tester import CookieTester
    from crawlers.http_client import HttpClient
    from crawlers.signer import Signer
    from crawlers.url_parser import URLParser
    from crawlers.user_home_crawler import UserHomeCrawler
    from crawlers.video_parser import VideoParser
    from downloader.scheduler import Scheduler


class AppContext:
    """应用上下文，持有全局共享的单例实例。"""

    def __init__(self) -> None:
        self.conn: sqlite3.Connection | None = None
        self.task_repo: TaskRepository | None = None
        self.task_item_repo: TaskItemRepository | None = None
        self.cookie_repo: CookieRepository | None = None
        self.config_repo: ConfigRepository | None = None
        self.metadata_repo: MetadataRepository | None = None
        self.scheduler: Scheduler | None = None
        self.http_client: HttpClient | None = None
        self.signer: Signer | None = None
        self.url_parser: URLParser | None = None
        self.video_parser: VideoParser | None = None
        self.user_home_crawler: UserHomeCrawler | None = None
        self.cookie_tester: CookieTester | None = None
        # v0.4.0：B 站组件
        self.bili_signer: BiliSigner | None = None
        self.bili_http_client: BiliHttpClient | None = None
        self.bili_url_parser: BiliURLParser | None = None
        self.bili_video_parser: BiliVideoParser | None = None
        self.bili_user_crawler: BiliUserCrawler | None = None
        self._bg_tasks: list[asyncio.Task] = []


ctx = AppContext()
