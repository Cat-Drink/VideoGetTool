"""pytest fixtures。

提供内存数据库、各 Repository、样本数据等 fixtures，供测试使用。
每个测试函数独立内存数据库，互不影响。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app import database
from app.models import Cookie, Subscription, Task, TaskItem
from app.repositories import (
    ConfigRepository,
    CookieRepository,
    MetadataRepository,
    SubscriptionRepository,
    TaskItemRepository,
    TaskRepository,
)
from crawlers.signer import DEFAULT_USER_AGENT
from crawlers.signer.abogus import ABogusSigner
from crawlers.signer.mstoken import MsTokenGenerator
from crawlers.signer.verify_fp import VerifyFpGenerator
from crawlers.signer.xbogus import XBogusSigner

# 测试数据文件路径
_VECTORS_PATH = Path(__file__).parent / "data" / "known_signer_vectors.json"


@pytest.fixture
def memory_db() -> sqlite3.Connection:
    """返回内存数据库连接（已初始化），测试结束后关闭。

    每个测试函数独立内存数据库，互不影响。
    """
    conn = database.get_memory_connection()
    yield conn
    conn.close()


@pytest.fixture
def task_repo(memory_db: sqlite3.Connection) -> TaskRepository:
    """返回 TaskRepository 实例。"""
    return TaskRepository(memory_db)


@pytest.fixture
def item_repo(memory_db: sqlite3.Connection) -> TaskItemRepository:
    """返回 TaskItemRepository 实例。"""
    return TaskItemRepository(memory_db)


@pytest.fixture
def cookie_repo(memory_db: sqlite3.Connection) -> CookieRepository:
    """返回 CookieRepository 实例。"""
    return CookieRepository(memory_db)


@pytest.fixture
def config_repo(memory_db: sqlite3.Connection) -> ConfigRepository:
    """返回 ConfigRepository 实例。"""
    return ConfigRepository(memory_db)


@pytest.fixture
def metadata_repo(memory_db: sqlite3.Connection) -> MetadataRepository:
    """返回 MetadataRepository 实例。"""
    return MetadataRepository(memory_db)


@pytest.fixture
def subscription_repo(memory_db: sqlite3.Connection) -> SubscriptionRepository:
    """返回 SubscriptionRepository 实例（v0.5.0 订阅模式）。"""
    return SubscriptionRepository(memory_db)


@pytest.fixture
def sample_subscription() -> Subscription:
    """返回一个可插入的 Subscription 实例（id=None）。"""
    return Subscription(
        id=None,
        url="https://www.douyin.com/user/MS4wLjABAAAA-test",
        sec_user_id="MS4wLjABAAAA-test",
        name="测试订阅",
        interval_minutes=30,
        enabled=1,
        max_items=30,
    )


@pytest.fixture
def sample_task() -> Task:
    """返回一个可插入的 Task 实例（id=None，时间戳由 Repository 填充）。"""
    return Task(
        id=None,
        source_type="single",
        source_url="https://www.douyin.com/video/123456",
        status="pending",
        total_items=1,
        completed_items=0,
        download_dir="C:/Downloads/VideoGetTool",
    )


@pytest.fixture
def sample_task_item(sample_task: Task, task_repo: TaskRepository) -> TaskItem:
    """先插入 sample_task 拿到 task_id，构造并返回 TaskItem（未插入，供测试按需插入）。"""
    task_id = task_repo.create(sample_task)
    return TaskItem(
        id=None,
        task_id=task_id,
        aweme_id="aweme_001",
        url="https://example.com/video.mp4",
        title="测试视频",
        author="测试作者",
        author_sec_id="sec_uid_001",
        type="video",
        duration="15s",
        image_count=None,
        cover_url="https://example.com/cover.jpg",
        status="pending",
        downloaded_bytes=0,
        total_bytes=1024000,
        retry_count=0,
        fail_reason=None,
        local_path=None,
    )


# ---- 签名算法测试 fixtures ----


@pytest.fixture
def default_user_agent() -> str:
    """返回与 Signer.DEFAULT_USER_AGENT 一致的 UA 字符串。"""
    return DEFAULT_USER_AGENT


@pytest.fixture
def known_vectors() -> dict:
    """加载 known_signer_vectors.json 中的已知输入/输出对。"""
    with open(_VECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def xbogus_signer() -> XBogusSigner:
    """返回固定时间戳的 XBogusSigner（确保确定性输出）。"""
    return XBogusSigner(timestamp=1700000000)


@pytest.fixture
def abogus_signer() -> ABogusSigner:
    """返回固定时间戳的 ABogusSigner（确保确定性输出）。"""
    return ABogusSigner(timestamp_ms=1700000000000)


@pytest.fixture
def mstoken_generator() -> MsTokenGenerator:
    """返回 MsTokenGenerator 实例。"""
    return MsTokenGenerator()


@pytest.fixture
def verify_fp_generator() -> VerifyFpGenerator:
    """返回 VerifyFpGenerator 实例。"""
    return VerifyFpGenerator()


# ---- HttpClient / Cookie 池测试 fixtures ----


class StubSigner:
    """签名 stub，返回固定签名 dict，供 HttpClient 测试使用。

    不调用真实签名算法，避免测试受签名算法变更影响。
    记录最后一次 sign 调用的参数，便于断言。
    """

    def __init__(self) -> None:
        self.last_url: str | None = None
        self.last_params: dict | None = None
        self.call_count: int = 0

    def sign(self, url: str, params: dict, user_agent: str | None = None) -> dict:
        """返回固定签名 dict，记录调用参数。"""
        self.last_url = url
        self.last_params = dict(params)
        self.call_count += 1
        return {
            "X-Bogus": "stub_xbogus_28chars________",
            "a_bogus": "stub_abogus_44chars_______________",
            "msToken": "stub_mstoken_172chars" + "x" * 150,
            "verifyFp": "verify_stub_" + "y" * 40,
        }


@pytest.fixture
def stub_signer() -> StubSigner:
    """返回 StubSigner 实例。"""
    return StubSigner()


@pytest.fixture
def sample_cookies(memory_db: sqlite3.Connection, cookie_repo: CookieRepository) -> list[Cookie]:
    """插入一组测试用 Cookie 并返回（含 valid/invalid/untested 三种状态）。

    - Cookie 1: valid, fail_count=0, last_used 较早
    - Cookie 2: valid, fail_count=1, last_used 较晚
    - Cookie 3: invalid, fail_count=3
    - Cookie 4: untested, fail_count=0
    """
    cookies = [
        Cookie(
            id=None,
            content="ttwid=fake_c1; msToken=fake_m1",
            label="账号A",
            status="valid",
            last_used="2026-07-11T08:00:00",
            last_check=None,
            fail_count=0,
            created_at="2026-07-11T07:00:00",
        ),
        Cookie(
            id=None,
            content="ttwid=fake_c2; msToken=fake_m2",
            label="账号B",
            status="valid",
            last_used="2026-07-11T10:00:00",
            last_check=None,
            fail_count=1,
            created_at="2026-07-11T07:00:00",
        ),
        Cookie(
            id=None,
            content="ttwid=fake_c3; msToken=fake_m3",
            label="账号C",
            status="invalid",
            last_used=None,
            last_check=None,
            fail_count=3,
            created_at="2026-07-11T07:00:00",
        ),
        Cookie(
            id=None,
            content="ttwid=fake_c4; msToken=fake_m4",
            label=None,
            status="untested",
            last_used=None,
            last_check=None,
            fail_count=0,
            created_at="2026-07-11T07:00:00",
        ),
    ]
    inserted: list[Cookie] = []
    for cookie in cookies:
        cookie_id = cookie_repo.add(cookie)
        inserted.append(cookie_repo.get_by_id(cookie_id))  # type: ignore[arg-type]
    return inserted
