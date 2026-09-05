"""订阅模式 REST API 集成测试（v0.4.1）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import SubscriptionItem, SubscriptionItemStatus
from app.repositories import SubscriptionRepository
from backend.state import ctx
from crawlers.url_parser import ParsedURL


@pytest.fixture
def api_client(memory_db) -> TestClient:
    """创建只挂载 subscription router 的 TestClient，并隔离全局上下文。"""
    from backend.api.subscription import router

    ctx_fields = ("subscription_repo", "url_parser", "subscription_scanner", "scheduler")
    previous = {field: getattr(ctx, field) for field in ctx_fields}

    ctx.subscription_repo = SubscriptionRepository(memory_db)
    url_parser = MagicMock(name="URLParser")
    url_parser.parse = AsyncMock(name="URLParser.parse")
    ctx.url_parser = url_parser

    scanner = MagicMock(name="SubscriptionScanner")
    scanner.scan_subscription = AsyncMock(
        name="SubscriptionScanner.scan_subscription",
        return_value=MagicMock(
            subscription_id=1,
            new_count=1,
            scanned_items=2,
            status="ok",
            error=None,
        ),
    )
    ctx.subscription_scanner = scanner

    scheduler = MagicMock(name="Scheduler")
    scheduler.add_task_items = MagicMock()
    ctx.scheduler = scheduler

    app = FastAPI()
    app.include_router(router, prefix="/api/subscription")
    client = TestClient(app)
    try:
        yield client
    finally:
        for field, value in previous.items():
            setattr(ctx, field, value)


def _home_parsed(url: str, sec_user_id: str) -> ParsedURL:
    """构造用户主页 URL 解析结果。"""
    return ParsedURL(
        type="user_home",
        url=url,
        aweme_id=None,
        sec_user_id=sec_user_id,
        original_text=url,
    )


def _video_parsed(url: str, aweme_id: str) -> ParsedURL:
    """构造视频 URL 解析结果。"""
    return ParsedURL(
        type="video",
        url=url,
        aweme_id=aweme_id,
        sec_user_id=None,
        original_text=url,
    )


class TestListAdd:
    """订阅列表与添加。"""

    def test_list_empty(self, api_client: TestClient) -> None:
        """空库返回空列表。"""
        response = api_client.get("/api/subscription/list")
        assert response.status_code == 200
        assert response.json() == []

    def test_add_and_list(self, api_client: TestClient) -> None:
        """添加后列表含订阅与新作品数。"""
        home_url = "https://www.douyin.com/user/MS4wLjABAAAA-test"
        ctx.url_parser.parse.return_value = _home_parsed(home_url, "MS4wLjABAAAA-test")

        response = api_client.post(
            "/api/subscription/add",
            json={"url": home_url, "interval_minutes": 60, "name": "测试"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["sec_user_id"] == "MS4wLjABAAAA-test"
        assert data["interval_minutes"] == 60
        assert data["enabled"] == 1
        assert data["new_count"] == 0

        listed = api_client.get("/api/subscription/list").json()
        assert len(listed) == 1
        assert listed[0]["name"] == "测试"

    def test_add_rejects_non_home_url(self, api_client: TestClient) -> None:
        """非主页链接返回 400。"""
        video_url = "https://www.douyin.com/video/123"
        ctx.url_parser.parse.return_value = _video_parsed(video_url, "123")
        response = api_client.post(
            "/api/subscription/add", json={"url": video_url}
        )
        assert response.status_code == 400
        assert "不是抖音用户主页" in response.json()["detail"]

    def test_add_rejects_invalid_interval(self, api_client: TestClient) -> None:
        """间隔超出范围返回 400。"""
        home_url = "https://www.douyin.com/user/MS4wLjABAAAA-test"
        ctx.url_parser.parse.return_value = _home_parsed(home_url, "MS4wLjABAAAA-test")
        response = api_client.post(
            "/api/subscription/add",
            json={"url": home_url, "interval_minutes": 1},
        )
        assert response.status_code == 400
        assert "扫描间隔" in response.json()["detail"]

    def test_add_duplicate_returns_409(self, api_client: TestClient) -> None:
        """重复订阅同一主页返回 409。"""
        home_url = "https://www.douyin.com/user/MS4wLjABAAAA-test"
        ctx.url_parser.parse.return_value = _home_parsed(home_url, "MS4wLjABAAAA-test")
        assert api_client.post(
            "/api/subscription/add", json={"url": home_url}
        ).status_code == 200
        response = api_client.post(
            "/api/subscription/add", json={"url": home_url}
        )
        assert response.status_code == 409


class TestUpdateDelete:
    """订阅更新与删除。"""

    def _create(self, api_client: TestClient) -> int:
        home_url = "https://www.douyin.com/user/MS4wLjABAAAA-test"
        ctx.url_parser.parse.return_value = _home_parsed(home_url, "MS4wLjABAAAA-test")
        return api_client.post(
            "/api/subscription/add", json={"url": home_url}
        ).json()["id"]

    def test_update_fields(self, api_client: TestClient) -> None:
        """更新名称/间隔/启用状态。"""
        sub_id = self._create(api_client)
        response = api_client.post(
            f"/api/subscription/{sub_id}/update",
            json={"name": "新名", "interval_minutes": 120, "enabled": 0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "新名"
        assert data["interval_minutes"] == 120
        assert data["enabled"] == 0

    def test_update_missing_returns_404(self, api_client: TestClient) -> None:
        """更新不存在的订阅返回 404。"""
        response = api_client.post(
            "/api/subscription/9999/update", json={"name": "x"}
        )
        assert response.status_code == 404

    def test_delete(self, api_client: TestClient) -> None:
        """删除订阅。"""
        sub_id = self._create(api_client)
        response = api_client.delete(f"/api/subscription/{sub_id}")
        assert response.status_code == 200
        assert api_client.get("/api/subscription/list").json() == []


class TestScanAndItems:
    """扫描与新作品处理。"""

    def _create(self, api_client: TestClient) -> int:
        home_url = "https://www.douyin.com/user/MS4wLjABAAAA-test"
        ctx.url_parser.parse.return_value = _home_parsed(home_url, "MS4wLjABAAAA-test")
        return api_client.post(
            "/api/subscription/add", json={"url": home_url}
        ).json()["id"]

    def _create_with_item(self, api_client: TestClient) -> tuple[int, int]:
        sub_id = self._create(api_client)
        item_id = ctx.subscription_repo.add_item(
            SubscriptionItem(
                id=None,
                subscription_id=sub_id,
                aweme_id="aweme-1",
                url="https://www.douyin.com/video/aweme-1",
                title="作品1",
                author="作者",
                type="video",
                status=SubscriptionItemStatus.NEW.value,
            )
        )
        return sub_id, item_id

    def test_scan_now(self, api_client: TestClient) -> None:
        """立即扫描返回结果并调用 scanner。"""
        sub_id = self._create(api_client)
        response = api_client.post(f"/api/subscription/{sub_id}/scan")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["new_count"] == 1
        ctx.subscription_scanner.scan_subscription.assert_awaited_once()

    def test_items_filter(self, api_client: TestClient) -> None:
        """按状态过滤作品列表。"""
        sub_id, _ = self._create_with_item(api_client)
        response = api_client.get(
            f"/api/subscription/{sub_id}/items", params={"status": "new"}
        )
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["aweme_id"] == "aweme-1"
        assert items[0]["status"] == SubscriptionItemStatus.NEW.value

    def test_items_invalid_status(self, api_client: TestClient) -> None:
        """非法状态参数返回 400。"""
        sub_id = self._create(api_client)
        response = api_client.get(
            f"/api/subscription/{sub_id}/items", params={"status": "bogus"}
        )
        assert response.status_code == 400

    def test_accept_marks_accepted(self, api_client: TestClient) -> None:
        """接受作品：标记为 accepted 并触发下载入队。"""
        sub_id, item_id = self._create_with_item(api_client)
        ctx.task_repo = MagicMock()
        ctx.task_item_repo = MagicMock()
        ctx.config_repo = MagicMock()
        ctx.config_repo.get.return_value = None
        ctx.cookie_repo = MagicMock()
        ctx.cookie_repo.get_valid.return_value = None

        response = api_client.post(f"/api/subscription/items/{item_id}/accept")
        assert response.status_code == 200
        assert response.json()["item_id"] == item_id
        item = ctx.subscription_repo.get_item(item_id)
        assert item is not None
        assert item.status == SubscriptionItemStatus.ACCEPTED.value

    def test_accept_already_processed(self, api_client: TestClient) -> None:
        """已处理的作品不可重复接受。"""
        sub_id, item_id = self._create_with_item(api_client)
        ctx.subscription_repo.update_item_status(
            item_id, SubscriptionItemStatus.SKIPPED.value
        )
        response = api_client.post(f"/api/subscription/items/{item_id}/accept")
        assert response.status_code == 400
        assert "已被处理" in response.json()["detail"]

    def test_skip(self, api_client: TestClient) -> None:
        """跳过作品。"""
        sub_id, item_id = self._create_with_item(api_client)
        response = api_client.post(f"/api/subscription/items/{item_id}/skip")
        assert response.status_code == 200
        item = ctx.subscription_repo.get_item(item_id)
        assert item is not None
        assert item.status == SubscriptionItemStatus.SKIPPED.value

    def test_skip_all_new(self, api_client: TestClient) -> None:
        """一键跳过全部新作品。"""
        sub_id, _ = self._create_with_item(api_client)
        ctx.subscription_repo.add_item(
            SubscriptionItem(
                id=None,
                subscription_id=sub_id,
                aweme_id="aweme-2",
                url="https://www.douyin.com/video/aweme-2",
                type="video",
                status=SubscriptionItemStatus.NEW.value,
            )
        )
        response = api_client.post(f"/api/subscription/{sub_id}/items/skip-all-new")
        assert response.status_code == 200
        assert response.json()["count"] == 2
        assert ctx.subscription_repo.count_new_items(sub_id) == 0
