"""订阅扫描器服务测试（v0.4.1）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Subscription, SubscriptionItemStatus
from backend.services.subscription_scanner import SubscriptionScanner
from crawlers.user_home_crawler import PostItem


def _post(aweme_id: str, title: str = "作品") -> PostItem:
    """构造 PostItem。"""
    return PostItem(
        aweme_id=aweme_id,
        title=title,
        author="测试作者",
        author_sec_id="sec-author",
        cover_url="https://example.com/cover.jpg",
        type="video",
        create_time="2026-01-01T00:00:00Z",
        duration="15s",
        image_count=None,
    )


def _build_scanner(
    memory_db,
    posts: list[PostItem],
    subscription_repo=None,
) -> tuple[SubscriptionScanner, MagicMock]:
    """构造 scanner，mock 掉 URLParser / UserHomeCrawler / CookieRepository。"""
    from app.repositories import SubscriptionRepository

    repo = subscription_repo or SubscriptionRepository(memory_db)
    url_parser = MagicMock(name="URLParser")
    url_parser.parse = AsyncMock(
        name="URLParser.parse",
        return_value=MagicMock(type="user_home", sec_user_id="sec-home", url="https://x"),
    )
    crawler = MagicMock(name="UserHomeCrawler")

    async def iter_posts(*args, **kwargs):
        for post in posts:
            yield post

    crawler.fetch_user_posts = MagicMock(side_effect=iter_posts)
    cookie_repo = MagicMock(name="CookieRepository")
    cookie_repo.get_valid.return_value = None
    scanner = SubscriptionScanner(
        subscription_repo=repo,
        url_parser=url_parser,
        user_home_crawler=crawler,
        cookie_repo=cookie_repo,
    )
    return scanner, crawler


def _make_subscription(**kwargs) -> Subscription:
    """构造订阅实例。"""
    return Subscription(
        id=None,
        url=kwargs.get("url", "https://www.douyin.com/user/sec-home"),
        sec_user_id=kwargs.get("sec_user_id", "sec-home"),
        name=kwargs.get("name", ""),
        interval_minutes=kwargs.get("interval_minutes", 30),
        enabled=kwargs.get("enabled", 1),
        max_items=kwargs.get("max_items", 30),
        last_scan_at=kwargs.get("last_scan_at"),
    )


class TestIsDue:
    """到期判断。"""

    def test_never_scanned_is_due(self) -> None:
        """从未扫描过 → 到期。"""
        assert SubscriptionScanner._is_due(_make_subscription(last_scan_at=None)) is True

    def test_disabled_not_due(self) -> None:
        """停用订阅不扫描。"""
        sub = _make_subscription(enabled=0, last_scan_at=None)
        assert SubscriptionScanner._is_due(sub) is False

    def test_recent_scan_not_due(self) -> None:
        """最近扫描过且未到间隔 → 不到期。"""
        recent = (datetime.now() - timedelta(minutes=5)).isoformat()
        sub = _make_subscription(interval_minutes=30, last_scan_at=recent)
        assert SubscriptionScanner._is_due(sub) is False

    def test_old_scan_is_due(self) -> None:
        """超过间隔 → 到期。"""
        old = (datetime.now() - timedelta(hours=2)).isoformat()
        sub = _make_subscription(interval_minutes=30, last_scan_at=old)
        assert SubscriptionScanner._is_due(sub) is True


class TestScanSubscription:
    """单订阅扫描。"""

    @pytest.mark.asyncio
    async def test_detects_new_items(self, memory_db) -> None:
        """首次扫描发现全部新作品并入库。"""
        scanner, crawler = _build_scanner(
            memory_db, posts=[_post("a1"), _post("a2"), _post("a3")]
        )
        sub_id = scanner.subscription_repo.create(_make_subscription())

        result = await scanner.scan_subscription(sub_id)

        assert result.status == "ok"
        assert result.new_count == 3
        assert result.scanned_items == 3
        items = scanner.subscription_repo.get_items(sub_id)
        assert len(items) == 3
        assert all(i.status == SubscriptionItemStatus.NEW.value for i in items)
        # 扫描状态更新
        sub = scanner.subscription_repo.get(sub_id)
        assert sub is not None
        assert sub.last_scan_status == "ok"
        assert sub.last_scan_at is not None

    @pytest.mark.asyncio
    async def test_second_scan_no_duplicates(self, memory_db) -> None:
        """重复扫描不会重复入库同一作品。"""
        scanner, _ = _build_scanner(
            memory_db, posts=[_post("a1"), _post("a2")]
        )
        sub_id = scanner.subscription_repo.create(_make_subscription())

        first = await scanner.scan_subscription(sub_id)
        second = await scanner.scan_subscription(sub_id)

        assert first.new_count == 2
        assert second.new_count == 0
        assert len(scanner.subscription_repo.get_items(sub_id)) == 2

    @pytest.mark.asyncio
    async def test_new_items_only(self, memory_db) -> None:
        """第三次扫描只发现真正新增的作品。"""
        scanner, crawler = _build_scanner(
            memory_db, posts=[_post("a1"), _post("a2")]
        )
        sub_id = scanner.subscription_repo.create(_make_subscription())
        await scanner.scan_subscription(sub_id)

        # 更换 crawler 返回值，模拟用户发了新作品
        async def iter_new(*args, **kwargs):
            for post in [_post("a1"), _post("a2"), _post("a3")]:
                yield post

        crawler.fetch_user_posts = MagicMock(side_effect=iter_new)
        result = await scanner.scan_subscription(sub_id)

        assert result.new_count == 1
        assert result.scanned_items == 3
        items = scanner.subscription_repo.get_items(sub_id)
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_scan_error_marks_error(self, memory_db) -> None:
        """扫描异常时记录 error 状态并返回错误结果。"""
        scanner, crawler = _build_scanner(memory_db, posts=[_post("a1")])
        # side_effect 为异常实例时，调用 fetch_user_posts 会直接抛出该异常
        crawler.fetch_user_posts.side_effect = RuntimeError("风控拦截")
        sub_id = scanner.subscription_repo.create(_make_subscription())

        result = await scanner.scan_subscription(sub_id)

        assert result.status == "error"
        assert "风控拦截" in (result.error or "")
        sub = scanner.subscription_repo.get(sub_id)
        assert sub is not None
        assert sub.last_scan_status == "error"
        assert sub.last_scan_error is not None

    @pytest.mark.asyncio
    async def test_scan_missing_subscription(self, memory_db) -> None:
        """订阅不存在返回错误结果。"""
        scanner, _ = _build_scanner(memory_db, posts=[_post("a1")])
        result = await scanner.scan_subscription(9999)
        assert result.status == "error"
        assert result.error == "订阅不存在"


class TestScanAllDue:
    """扫描全部到期订阅。"""

    @pytest.mark.asyncio
    async def test_only_due_subscriptions_scanned(self, memory_db) -> None:
        """只扫描到期订阅。"""
        scanner, _ = _build_scanner(memory_db, posts=[_post("a1")])
        due_sub_id = scanner.subscription_repo.create(_make_subscription(last_scan_at=None))
        recent_scan_at = (datetime.now() - timedelta(minutes=1)).isoformat()
        recent_sub_id = scanner.subscription_repo.create(
            _make_subscription(
                url="https://www.douyin.com/user/sec-recent",
                sec_user_id="sec-recent",
                last_scan_at=recent_scan_at,
            )
        )

        results = await scanner.scan_all_due()

        assert len(results) == 1
        assert results[0].subscription_id == due_sub_id
        # recent 订阅未被扫描（last_scan_at 保持原值）
        recent = scanner.subscription_repo.get(recent_sub_id)
        assert recent is not None
        assert recent.last_scan_at == recent_scan_at

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, memory_db) -> None:
        """start/stop 幂等且可正常停止。"""
        scanner, _ = _build_scanner(memory_db, posts=[])
        await scanner.start()
        assert scanner._task is not None
        await scanner.start()  # 幂等
        await scanner.stop()
        assert scanner._task is None

    @pytest.mark.asyncio
    async def test_broadcast_on_new_items(self, memory_db, monkeypatch) -> None:
        """发现新作品时广播 WebSocket 事件。"""
        scanner, _ = _build_scanner(memory_db, posts=[_post("a1")])
        sub_id = scanner.subscription_repo.create(_make_subscription())

        broadcast_calls = []
        manager_mock = MagicMock()
        manager_mock.broadcast = AsyncMock(side_effect=lambda msg: broadcast_calls.append(msg))
        # 替换真实 ws 模块的 manager（backend.api.ws 可正常导入）
        monkeypatch.setattr("backend.api.ws.manager", manager_mock)

        await scanner.scan_subscription(sub_id)

        assert len(broadcast_calls) == 1
        assert broadcast_calls[0]["type"] == "subscription_update"
        assert broadcast_calls[0]["subscription_id"] == sub_id
        assert broadcast_calls[0]["new_count"] == 1
