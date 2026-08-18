"""WebSocket 进度推送测试。"""

from __future__ import annotations

import asyncio

import pytest

from app.models import Task, TaskItem
from app.repositories import TaskItemRepository, TaskRepository


@pytest.mark.asyncio
async def test_ws_pushes_all_statuses(memory_db):
    """WebSocket 推送 downloading/completed/failed 三种状态的任务项。"""
    from backend.api.ws import _push_progress_updates
    from backend.state import ctx

    task_repo = TaskRepository(memory_db)
    item_repo = TaskItemRepository(memory_db)
    ctx.task_item_repo = item_repo
    ctx.scheduler = None  # 不依赖 scheduler

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
            downloaded_bytes=50,
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
            total_bytes=200,
            downloaded_bytes=200,
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
            total_bytes=0,
            downloaded_bytes=0,
        )
    )

    received: list[dict] = []

    class FakeWS:
        async def send_json(self, data):
            received.append(data)

    # 共享轮询任务通过 manager.broadcast 广播，需要先把 FakeWS 注册进管理器
    from backend.api.ws import manager

    fake_ws = FakeWS()
    manager._connections.append(fake_ws)

    stop_event = asyncio.Event()
    push_task = asyncio.create_task(_push_progress_updates(stop_event))

    await asyncio.sleep(1.1)
    stop_event.set()
    await push_task

    progress_msgs = [m for m in received if m["type"] == "progress"]
    assert len(progress_msgs) >= 1

    updates = progress_msgs[0]["updates"]
    update_map = {u["task_item_id"]: u for u in updates}

    assert downloading_id in update_map
    assert completed_id in update_map
    assert failed_id in update_map

    assert update_map[completed_id]["progress"] == 100.0
    assert update_map[completed_id]["status"] == "completed"

    assert update_map[downloading_id]["progress"] == 50.0

    assert update_map[failed_id]["status"] == "failed"
