"""下载 API 端点测试。"""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import Task, TaskItem
from app.repositories import TaskItemRepository, TaskRepository
from backend.state import ctx


@pytest.fixture
def api_client(memory_db):
    """创建带内存数据库的 FastAPI TestClient（同步版，绕过线程问题）。"""
    from unittest.mock import MagicMock

    from app.repositories import ConfigRepository, CookieRepository, MetadataRepository

    ctx.conn = memory_db
    ctx.task_repo = TaskRepository(memory_db)
    ctx.task_item_repo = TaskItemRepository(memory_db)
    ctx.cookie_repo = CookieRepository(memory_db)
    ctx.config_repo = ConfigRepository(memory_db)
    ctx.metadata_repo = MetadataRepository(memory_db)

    mock_scheduler = MagicMock()
    ctx.scheduler = mock_scheduler

    from backend.api.download import router

    app = FastAPI()
    app.include_router(router, prefix="/api/download")

    # 直接用 TestClient 默认后端
    client = TestClient(app)
    yield client
    ctx.conn = None
    ctx.task_repo = None
    ctx.task_item_repo = None
    ctx.cookie_repo = None
    ctx.config_repo = None
    ctx.metadata_repo = None
    ctx.scheduler = None


class TestTaskItemProgress:
    """任务项进度 API 测试。"""

    def test_completed_item_returns_100_progress(self, api_client, memory_db):
        """完成任务项 API 返回 progress=100。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="downloading",
                download_dir="/tmp",
            )
        )
        item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="aw1",
                url="http://x/1",
                type="video",
                status="completed",
                total_bytes=0,
                downloaded_bytes=0,
            )
        )

        resp = api_client.get(f"/api/download/tasks/{tid}/items")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "completed"
        assert data[0]["progress"] == 100.0

    def test_downloading_item_progress_from_bytes(self, api_client, memory_db):
        """下载中任务项 progress 由字节数计算。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="downloading",
                download_dir="/tmp",
            )
        )
        item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="aw1",
                url="http://x/1",
                type="video",
                status="downloading",
                total_bytes=200,
                downloaded_bytes=150,
            )
        )

        resp = api_client.get(f"/api/download/tasks/{tid}/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["progress"] == 75.0


class TestRetryAllFailed:
    """全部失败重试 API 测试。"""

    def test_retries_all_failed_items_and_preserves_active_items(self, api_client, memory_db):
        """全部失败项重置并入队，进行中的任务保持不变。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="failed",
                download_dir="/tmp",
            )
        )
        failed_ids = [
            item_repo.create(
                TaskItem(
                    id=None,
                    task_id=tid,
                    aweme_id=f"failed-{i}",
                    url=f"http://x/{i}",
                    type="video",
                    status="failed",
                    downloaded_bytes=100,
                    total_bytes=200,
                    fail_reason="网络错误",
                    local_path="/tmp/file.part",
                )
            )
            for i in range(2)
        ]
        active_id = item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="active",
                url="http://x/active",
                type="video",
                status="downloading",
                downloaded_bytes=50,
                total_bytes=100,
            )
        )

        resp = api_client.post("/api/download/retry-all")

        assert resp.status_code == 200
        assert resp.json()["retried_count"] == 2
        for item_id in failed_ids:
            item = item_repo.get(item_id)
            assert item.status == "pending"
            assert item.downloaded_bytes == 0
            assert item.total_bytes == 0
            assert item.fail_reason is None
            assert item.local_path is None
        active = item_repo.get(active_id)
        assert active.status == "downloading"

        assert ctx.scheduler.add_task_items.call_count == 1
        queued_items = ctx.scheduler.add_task_items.call_args.args[0]
        assert {item.id for item in queued_items} == set(failed_ids)

    def test_retry_all_with_no_failed_items_returns_zero(self, api_client, memory_db):
        """没有失败项时不入队并返回 0。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)
        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="downloading",
                download_dir="/tmp",
            )
        )
        item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="active",
                url="http://x/active",
                type="video",
                status="downloading",
            )
        )

        resp = api_client.post("/api/download/retry-all")

        assert resp.status_code == 200
        assert resp.json()["retried_count"] == 0
        assert "没有失败任务" in resp.json()["message"]


class TestClearCompleted:
    """清空已完成 API 测试。"""

    def test_clear_only_removes_completed_items(self, api_client, memory_db):
        """清空只删除已完成项，保留进行中/失败项。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="downloading",
                download_dir="/tmp",
            )
        )
        completed_id = item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="c1",
                url="http://x/c1",
                type="video",
                status="completed",
            )
        )
        downloading_id = item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="d1",
                url="http://x/d1",
                type="video",
                status="downloading",
            )
        )
        failed_id = item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="f1",
                url="http://x/f1",
                type="video",
                status="failed",
            )
        )

        resp = api_client.post("/api/download/clear-completed")
        assert resp.status_code == 200

        assert item_repo.get(completed_id) is None
        assert item_repo.get(downloading_id) is not None
        assert item_repo.get(failed_id) is not None

    def test_clear_completed_does_not_block_other_items(self, api_client, memory_db):
        """清空完成后进行中项状态和进度不变。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="downloading",
                download_dir="/tmp",
            )
        )
        downloading_id = item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="d1",
                url="http://x/d1",
                type="video",
                status="downloading",
                total_bytes=100,
                downloaded_bytes=97,
            )
        )
        item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="c1",
                url="http://x/c1",
                type="video",
                status="completed",
            )
        )

        resp = api_client.post("/api/download/clear-completed")
        assert resp.status_code == 200

        item = item_repo.get(downloading_id)
        assert item.status == "downloading"
        assert item.downloaded_bytes == 97
        assert item.total_bytes == 100


class TestVerifyCompletedFiles:
    """文件校验 API 测试。"""

    def test_verify_all_files_exist(self, api_client, memory_db):
        """所有文件存在时校验通过，无 missing_items。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="completed",
                download_dir="/tmp",
            )
        )
        # 创建一个临时文件用于校验
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
            f.write(b"fake video content")
            temp_path = f.name

        try:
            item_repo.create(
                TaskItem(
                    id=None,
                    task_id=tid,
                    aweme_id="v1",
                    url="http://x/v1",
                    type="video",
                    status="completed",
                    local_path=temp_path,
                )
            )

            resp = api_client.post("/api/download/verify")
            assert resp.status_code == 200
            data = resp.json()
            assert data["verified_count"] == 1
            assert data["missing_count"] == 0
            assert data["missing_items"] == []
        finally:
            os.unlink(temp_path)

    def test_verify_file_missing(self, api_client, memory_db):
        """文件不存在时标记为 missing 并置为 failed。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="completed",
                download_dir="/tmp",
            )
        )
        item_id = item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="v1",
                url="http://x/v1",
                type="video",
                status="completed",
                local_path="C:/nonexistent/path/file.mp4",
            )
        )

        resp = api_client.post("/api/download/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified_count"] == 1
        assert data["missing_count"] == 1
        assert len(data["missing_items"]) == 1
        assert data["missing_items"][0]["id"] == item_id

        # 验证状态已更新为 failed
        item = item_repo.get(item_id)
        assert item.status == "failed"
        assert "文件不存在" in (item.fail_reason or "")

    def test_verify_with_normalized_path(self, api_client, memory_db):
        """路径规范化后能找到文件（混合正反斜杠路径）。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="completed",
                download_dir="/tmp",
            )
        )
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
            f.write(b"fake video content")
            temp_path = f.name

        try:
            # 用反斜杠路径存储（Windows 常见问题）
            win_style_path = temp_path.replace("/", "\\")
            item_repo.create(
                TaskItem(
                    id=None,
                    task_id=tid,
                    aweme_id="v1",
                    url="http://x/v1",
                    type="video",
                    status="completed",
                    local_path=win_style_path,
                )
            )

            resp = api_client.post("/api/download/verify")
            assert resp.status_code == 200
            data = resp.json()
            assert data["verified_count"] == 1
            assert data["missing_count"] == 0
            assert data["missing_items"] == []
        finally:
            os.unlink(temp_path)

    def test_verify_empty_local_path(self, api_client, memory_db):
        """local_path 为空时标记为 missing。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="completed",
                download_dir="/tmp",
            )
        )
        item_id = item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="v1",
                url="http://x/v1",
                type="video",
                status="completed",
                local_path=None,
            )
        )

        resp = api_client.post("/api/download/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified_count"] == 1
        assert data["missing_count"] == 1

        item = item_repo.get(item_id)
        assert item.status == "failed"

    def test_verify_empty_completed_list(self, api_client, memory_db):
        """没有 completed 项时返回 0 计数。"""
        resp = api_client.post("/api/download/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified_count"] == 0
        assert data["missing_count"] == 0
        assert data["missing_items"] == []

    def test_verify_only_checks_completed_items(self, api_client, memory_db):
        """只校验 completed 状态项，不检查其他状态。"""
        task_repo = TaskRepository(memory_db)
        item_repo = TaskItemRepository(memory_db)

        tid = task_repo.create(
            Task(
                id=None,
                source_type="single",
                source_url="x",
                status="downloading",
                download_dir="/tmp",
            )
        )
        item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="d1",
                url="http://x/d1",
                type="video",
                status="downloading",
                local_path="C:/nonexistent/path/file.mp4",
            )
        )
        item_repo.create(
            TaskItem(
                id=None,
                task_id=tid,
                aweme_id="f1",
                url="http://x/f1",
                type="video",
                status="failed",
                local_path="C:/nonexistent/path/file.mp4",
            )
        )

        resp = api_client.post("/api/download/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified_count"] == 0
        assert data["missing_count"] == 0
