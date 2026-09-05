"""订阅模式 Repository 测试（v0.4.1）。"""

from __future__ import annotations

import sqlite3

from app.models import Subscription, SubscriptionItem, SubscriptionItemStatus
from app.repositories import SubscriptionRepository


def _make_item(sub_id: int, aweme_id: str = "aweme-1", **kwargs) -> SubscriptionItem:
    """构造订阅作品实例。"""
    return SubscriptionItem(
        id=None,
        subscription_id=sub_id,
        aweme_id=aweme_id,
        url=f"https://www.douyin.com/video/{aweme_id}",
        title=kwargs.get("title", "测试作品"),
        author=kwargs.get("author", "测试作者"),
        type=kwargs.get("type", "video"),
        status=kwargs.get("status", SubscriptionItemStatus.NEW.value),
    )


class TestSubscriptionCrud:
    """订阅表 CRUD 测试。"""

    def test_create_and_get(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """创建后可按 id 查询，字段完整。"""
        sub_id = subscription_repo.create(sample_subscription)
        assert sub_id > 0
        sub = subscription_repo.get(sub_id)
        assert sub is not None
        assert sub.url == sample_subscription.url
        assert sub.sec_user_id == sample_subscription.sec_user_id
        assert sub.interval_minutes == 30
        assert sub.enabled == 1
        assert sub.max_items == 30
        assert sub.created_at
        assert sub.updated_at

    def test_get_missing_returns_none(
        self, subscription_repo: SubscriptionRepository
    ) -> None:
        """查询不存在的订阅返回 None。"""
        assert subscription_repo.get(9999) is None

    def test_get_by_sec_user_id(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """按 sec_user_id 查询。"""
        sub_id = subscription_repo.create(sample_subscription)
        found = subscription_repo.get_by_sec_user_id(sample_subscription.sec_user_id)
        assert found is not None
        assert found.id == sub_id
        assert subscription_repo.get_by_sec_user_id("not-exist") is None

    def test_exists_sec_user_id(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """去重判断。"""
        subscription_repo.create(sample_subscription)
        assert subscription_repo.exists_sec_user_id(sample_subscription.sec_user_id) is True
        assert subscription_repo.exists_sec_user_id("other") is False

    def test_get_all_and_enabled(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """get_all 返回全部，get_enabled 只返回启用项。"""
        subscription_repo.create(sample_subscription)
        disabled = Subscription(
            id=None,
            url="https://www.douyin.com/user/MS4wLjABAAAA-disabled",
            sec_user_id="MS4wLjABAAAA-disabled",
            enabled=0,
        )
        subscription_repo.create(disabled)
        assert len(subscription_repo.get_all()) == 2
        enabled = subscription_repo.get_enabled()
        assert len(enabled) == 1
        assert enabled[0].sec_user_id == sample_subscription.sec_user_id

    def test_update_partial(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """仅更新传入字段，未传字段保持不变。"""
        sub_id = subscription_repo.create(sample_subscription)
        subscription_repo.update(sub_id, name="新名称", enabled=0, interval_minutes=60)
        sub = subscription_repo.get(sub_id)
        assert sub is not None
        assert sub.name == "新名称"
        assert sub.enabled == 0
        assert sub.interval_minutes == 60
        # 未更新字段保持原值
        assert sub.max_items == 30

    def test_update_scan_result(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """更新扫描状态字段。"""
        sub_id = subscription_repo.create(sample_subscription)
        subscription_repo.update(
            sub_id, last_scan_at="2026-01-01T00:00:00", last_scan_status="ok", last_scan_error=None
        )
        sub = subscription_repo.get(sub_id)
        assert sub is not None
        assert sub.last_scan_at == "2026-01-01T00:00:00"
        assert sub.last_scan_status == "ok"
        assert sub.last_scan_error is None

    def test_delete_cascades_items(
        self,
        subscription_repo: SubscriptionRepository,
        sample_subscription: Subscription,
    ) -> None:
        """删除订阅后其作品记录级联删除。"""
        sub_id = subscription_repo.create(sample_subscription)
        subscription_repo.add_item(_make_item(sub_id))
        assert len(subscription_repo.get_items(sub_id)) == 1
        subscription_repo.delete(sub_id)
        assert subscription_repo.get(sub_id) is None
        assert len(subscription_repo.get_items(sub_id)) == 0


class TestSubscriptionItemCrud:
    """订阅作品表 CRUD 测试。"""

    def test_add_and_get_item(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """添加作品后可查询。"""
        sub_id = subscription_repo.create(sample_subscription)
        item_id = subscription_repo.add_item(_make_item(sub_id))
        item = subscription_repo.get_item(item_id)
        assert item is not None
        assert item.subscription_id == sub_id
        assert item.aweme_id == "aweme-1"
        assert item.status == SubscriptionItemStatus.NEW.value

    def test_add_item_dedup(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """相同 (subscription_id, aweme_id) 只保留一条。"""
        sub_id = subscription_repo.create(sample_subscription)
        first = subscription_repo.add_item(_make_item(sub_id))
        second = subscription_repo.add_item(_make_item(sub_id))
        assert first == second
        assert len(subscription_repo.get_items(sub_id)) == 1

    def test_get_item_by_aweme_id(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """按 aweme_id 查询用于新作品去重。"""
        sub_id = subscription_repo.create(sample_subscription)
        subscription_repo.add_item(_make_item(sub_id, "aweme-1"))
        assert subscription_repo.get_item_by_aweme_id(sub_id, "aweme-1") is not None
        assert subscription_repo.get_item_by_aweme_id(sub_id, "aweme-2") is None

    def test_get_items_filter_and_limit(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """按状态过滤与数量限制。"""
        sub_id = subscription_repo.create(sample_subscription)
        for i in range(3):
            subscription_repo.add_item(_make_item(sub_id, f"aweme-{i}"))
        subscription_repo.add_item(
            _make_item(
                sub_id,
                "aweme-done",
                status=SubscriptionItemStatus.SKIPPED.value,
            )
        )
        new_items = subscription_repo.get_items(sub_id, status=SubscriptionItemStatus.NEW.value)
        assert len(new_items) == 3
        assert all(i.status == SubscriptionItemStatus.NEW.value for i in new_items)
        limited = subscription_repo.get_items(sub_id, limit=2)
        assert len(limited) == 2

    def test_count_new_items(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """统计新作品数量。"""
        sub_id = subscription_repo.create(sample_subscription)
        assert subscription_repo.count_new_items(sub_id) == 0
        subscription_repo.add_item(_make_item(sub_id, "aweme-1"))
        subscription_repo.add_item(_make_item(sub_id, "aweme-2"))
        assert subscription_repo.count_new_items(sub_id) == 2
        assert subscription_repo.count_new_items_map() == {sub_id: 2}

    def test_update_item_status(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """更新作品状态。"""
        sub_id = subscription_repo.create(sample_subscription)
        item_id = subscription_repo.add_item(_make_item(sub_id))
        subscription_repo.update_item_status(item_id, SubscriptionItemStatus.ACCEPTED.value)
        item = subscription_repo.get_item(item_id)
        assert item is not None
        assert item.status == SubscriptionItemStatus.ACCEPTED.value

    def test_update_items_status_batch(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """批量更新状态（一键跳过）。"""
        sub_id = subscription_repo.create(sample_subscription)
        for i in range(3):
            subscription_repo.add_item(_make_item(sub_id, f"aweme-{i}"))
        count = subscription_repo.update_items_status(
            sub_id,
            from_status=SubscriptionItemStatus.NEW.value,
            to_status=SubscriptionItemStatus.SKIPPED.value,
        )
        assert count == 3
        assert subscription_repo.count_new_items(sub_id) == 0

    def test_delete_item(
        self, subscription_repo: SubscriptionRepository, sample_subscription: Subscription
    ) -> None:
        """删除单个作品。"""
        sub_id = subscription_repo.create(sample_subscription)
        item_id = subscription_repo.add_item(_make_item(sub_id))
        subscription_repo.delete_item(item_id)
        assert subscription_repo.get_item(item_id) is None


class TestMigration:
    """v5 迁移测试。"""

    def test_v5_tables_created(self, memory_db: sqlite3.Connection) -> None:
        """内存库初始化后应包含订阅两张表。"""
        tables = {
            row["name"]
            for row in memory_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "subscriptions" in tables
        assert "subscription_items" in tables

    def test_v5_foreign_key_cascade(self, memory_db: sqlite3.Connection) -> None:
        """外键 ON DELETE CASCADE 生效。"""
        repo = SubscriptionRepository(memory_db)
        sub_id = repo.create(
            Subscription(
                id=None,
                url="https://www.douyin.com/user/test",
                sec_user_id="test",
            )
        )
        repo.add_item(_make_item(sub_id))
        repo.delete(sub_id)
        assert memory_db.execute(
            "SELECT COUNT(*) FROM subscription_items"
        ).fetchone()[0] == 0
