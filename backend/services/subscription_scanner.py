"""订阅扫描服务（v0.4.1 订阅模式）。

后台定时任务：周期性扫描所有启用的抖音用户主页订阅，
检测用户是否有新作品发布；发现新作品时写入 subscription_items（status='new'），
并通过 WebSocket 广播通知前端。

设计要点:
    - 通过依赖注入接收 Repository / URLParser / UserHomeCrawler / CookieRepository，
      便于单元测试 mock
    - 每个订阅可独立设置扫描间隔（interval_minutes，默认 30 分钟）
    - 新作品判定：以 (subscription_id, aweme_id) 是否已存在于 subscription_items 为准
    - 扫描循环每 TICK_SECONDS 秒检查一次到期订阅，避免忙轮询
    - 同一订阅并发扫描保护：per-subscription asyncio.Lock
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.models import Subscription, SubscriptionItem, SubscriptionItemStatus, now_iso

if TYPE_CHECKING:
    from app.repositories import CookieRepository, SubscriptionRepository
    from crawlers.http_client import HttpClient
    from crawlers.url_parser import URLParser
    from crawlers.user_home_crawler import UserHomeCrawler

logger = logging.getLogger(__name__)

# 扫描循环 tick 间隔（秒）：每 30 秒检查一次是否有订阅到期
TICK_SECONDS: int = 30


@dataclass(frozen=True)
class ScanResult:
    """单次订阅扫描结果。"""

    subscription_id: int
    new_count: int = 0
    status: str = "ok"  # ok / error
    error: str | None = None
    scanned_items: int = 0


@dataclass
class SubscriptionScanner:
    """订阅后台扫描器。

    生命周期:
        start() → 启动后台循环；stop() → 停止并等待退出。

    依赖注入:
        subscription_repo: SubscriptionRepository
        url_parser: URLParser（解析主页 URL → sec_user_id）
        user_home_crawler: UserHomeCrawler（拉取主页作品）
        cookie_repo: CookieRepository（获取有效 Cookie）
        http_client: HttpClient（扫描时更新 Cookie 使用时间）
    """

    subscription_repo: SubscriptionRepository
    url_parser: URLParser
    user_home_crawler: UserHomeCrawler
    cookie_repo: CookieRepository
    http_client: HttpClient | None = None
    tick_seconds: int = TICK_SECONDS
    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _locks: dict[int, asyncio.Lock] = field(default_factory=dict, init=False, repr=False)

    # === 生命周期 ===

    async def start(self) -> None:
        """启动后台扫描循环（幂等）。"""
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="subscription-scanner")
        logger.info("订阅扫描器已启动（tick=%ss）", self.tick_seconds)

    async def stop(self) -> None:
        """停止后台扫描循环。"""
        self._stop_event.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("订阅扫描器已停止")

    # === 后台循环 ===

    async def _run_loop(self) -> None:
        """主循环：周期检查到期订阅并扫描。"""
        while not self._stop_event.is_set():
            try:
                await self.scan_all_due()
            except Exception:
                logger.exception("订阅扫描循环异常")
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.tick_seconds
                )

    # === 扫描 ===

    async def scan_all_due(self) -> list[ScanResult]:
        """扫描所有到期（且启用）的订阅。

        Returns:
            各订阅扫描结果列表（失败订阅的 result.status == 'error'）。
        """
        subscriptions = self.subscription_repo.get_enabled()
        results: list[ScanResult] = []
        for sub in subscriptions:
            if self._is_due(sub):
                results.append(await self.scan_subscription(sub.id))
        return results

    @staticmethod
    def _is_due(sub: Subscription) -> bool:
        """判断订阅是否到期需要扫描。"""
        if not sub.enabled:
            return False
        if not sub.last_scan_at:
            return True
        try:
            last = datetime.fromisoformat(sub.last_scan_at)
        except (ValueError, TypeError):
            return True
        return datetime.now() - last >= timedelta(minutes=sub.interval_minutes)

    async def scan_subscription(self, subscription_id: int) -> ScanResult:
        """扫描单个订阅：拉取主页作品，检测并入库新作品。

        并发保护：同一订阅同时只有一个扫描协程（asyncio.Lock）。
        """
        lock = self._locks.setdefault(subscription_id, asyncio.Lock())
        async with lock:
            sub = self.subscription_repo.get(subscription_id)
            if sub is None:
                return ScanResult(subscription_id, status="error", error="订阅不存在")

            try:
                # 1. 解析主页 URL → sec_user_id（缺失时回退订阅中已有值）
                sec_user_id = sub.sec_user_id
                try:
                    parsed = await self.url_parser.parse(sub.url)
                    if parsed.type == "user_home" and parsed.sec_user_id:
                        sec_user_id = parsed.sec_user_id
                except Exception as e:
                    logger.warning("订阅 %d URL 解析失败: %s", subscription_id, e)

                # 2. 获取一个有效 Cookie
                cookie = ""
                if self.cookie_repo is not None:
                    valid = self.cookie_repo.get_valid()
                    if valid is not None:
                        cookie = valid.content
                        self.cookie_repo.update_last_used(valid.id, now_iso())

                # 3. 拉取主页作品并检测新作品
                from crawlers.user_home_crawler import HomeFilters

                filters = HomeFilters(type_filter="all", max_count=sub.max_items)
                new_count = 0
                scanned_items = 0
                async for post in self.user_home_crawler.fetch_user_posts(
                    sec_user_id, filters, cookie
                ):
                    scanned_items += 1
                    existing = self.subscription_repo.get_item_by_aweme_id(
                        subscription_id, post.aweme_id
                    )
                    if existing is not None:
                        continue
                    item = SubscriptionItem(
                        id=None,
                        subscription_id=subscription_id,
                        aweme_id=post.aweme_id,
                        url=f"https://www.douyin.com/video/{post.aweme_id}",
                        title=post.title,
                        author=post.author,
                        author_sec_id=post.author_sec_id,
                        type=post.type,
                        duration=post.duration,
                        image_count=post.image_count,
                        cover_url=post.cover_url,
                        publish_time=post.create_time,
                        status=SubscriptionItemStatus.NEW.value,
                    )
                    self.subscription_repo.add_item(item)
                    new_count += 1

                # 4. 更新扫描状态
                self.subscription_repo.update(
                    subscription_id,
                    last_scan_at=now_iso(),
                    last_scan_status="ok",
                    last_scan_error=None,
                )
                logger.info(
                    "订阅 %d 扫描完成: 检查 %d 条，新增 %d 条",
                    subscription_id,
                    scanned_items,
                    new_count,
                )

                # 5. WebSocket 广播（有新作品时）
                if new_count > 0:
                    await self._broadcast(subscription_id, new_count)

                return ScanResult(
                    subscription_id=subscription_id,
                    new_count=new_count,
                    status="ok",
                    scanned_items=scanned_items,
                )
            except Exception as e:
                logger.exception("订阅 %d 扫描失败", subscription_id)
                self.subscription_repo.update(
                    subscription_id,
                    last_scan_at=now_iso(),
                    last_scan_status="error",
                    last_scan_error=str(e)[:500],
                )
                return ScanResult(
                    subscription_id=subscription_id,
                    status="error",
                    error=str(e)[:500],
                )

    # === 辅助 ===

    async def _broadcast(self, subscription_id: int, new_count: int) -> None:
        """通过 WebSocket 广播订阅更新事件（延迟 import 避免循环依赖）。"""
        try:
            from backend.api import ws as ws_router

            await ws_router.manager.broadcast(
                {
                    "type": "subscription_update",
                    "subscription_id": subscription_id,
                    "new_count": new_count,
                    "timestamp": now_iso(),
                }
            )
        except Exception:
            logger.exception("广播 subscription_update 消息失败")
