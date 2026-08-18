"""任务调度器模块。

实现并发控制、队列管理、暂停/恢复、去重、与进度节流器集成。
严格遵循设计文档 5.1 节（组件结构）、5.4 节（暂停/恢复）、2.4 节（并发控制）。

职责边界（设计文档 5.6 节 + 8.2 节）：
- Scheduler 负责队列管理、暂停/恢复、去重、回调触发
- Scheduler **不**直接处理 HTTP 下载（归 Downloader）
- 并发信号量由 Scheduler 创建并注入 Downloader，Downloader 在 _download_single_file
  内部 acquire/release；Scheduler 的 _run_download 不重复 acquire
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx

from app.logger import get_logger
from app.models import TaskItem
from app.repositories import TaskItemRepository, TaskRepository
from downloader.downloader import Downloader
from downloader.progress_reporter import ProgressReporter, ProgressUpdate

if TYPE_CHECKING:
    from app.repositories import CookieRepository
    from crawlers.video_parser import VideoParser

logger = get_logger(__name__)

# === 常量（设计文档 2.4 节）===

# 默认并发数 3
DEFAULT_MAX_CONCURRENT: int = 3

# 并发上限 10
MAX_CONCURRENT_LIMIT: int = 10

# 下载客户端连接超时（秒）
DEFAULT_DOWNLOAD_CONNECT_TIMEOUT: float = 30.0

# 下载客户端读取超时（秒）
DEFAULT_DOWNLOAD_READ_TIMEOUT: float = 60.0

# 下载客户端默认请求头（抖音 CDN 要求 Referer 和 User-Agent，否则返回 403）
DOWNLOAD_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douyin.com/",
}


class Scheduler:
    """任务调度器。

    管理待下载队列，创建 asyncio.Task 执行下载，提供暂停/恢复/去重能力。
    通过回调函数通知外部（不直接依赖 Qt），由后续 ``worker/`` 里程碑桥接到 Qt 信号。

    并发控制通过 ``asyncio.Semaphore`` 实现，信号量由 Scheduler 创建并注入 Downloader。
    Downloader 在 ``_download_single_file`` 内部 acquire/release 信号量，
    图集子下载也受同一信号量约束（设计文档 2.4 节）。
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        http_client: httpx.AsyncClient | None = None,
        on_item_completed: Callable[[int], None] | None = None,
        on_item_failed: Callable[[int, str], None] | None = None,
        on_progress: Callable[[list[ProgressUpdate]], None] | None = None,
        video_parser: VideoParser | None = None,
        cookie_repository: CookieRepository | None = None,
    ) -> None:
        """初始化调度器。

        Args:
            conn: SQLite 连接（用于状态查询与更新）
            max_concurrent: 最大并发数，clamp 到 [1, 10]
            http_client: httpx 异步客户端；为 None 时内部创建
            on_item_completed: 下载成功回调，参数 task_item_id
            on_item_failed: 下载失败回调，参数 (task_item_id, fail_reason)
            on_progress: 进度批量回调，参数 list[ProgressUpdate]
            video_parser: 图集直链失效重新解析依赖（v0.1.7 plan 6.6）；
                为 None 时图集 4xx 直接失败不重新解析
            cookie_repository: 重新解析时取有效 Cookie（v0.1.7 plan 6.6）；
                为 None 时图集 4xx 直接失败不重新解析
        """
        self._conn = conn
        self._item_repo = TaskItemRepository(conn)
        self._task_repo = TaskRepository(conn)
        self._on_item_completed = on_item_completed
        self._on_item_failed = on_item_failed

        # clamp 并发数到 [1, 10]
        self._max_concurrent = max(1, min(max_concurrent, MAX_CONCURRENT_LIMIT))
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        # httpx 客户端：外部注入或内部创建
        # follow_redirects=True：抖音短链与 CDN 直链均可能返回 302，需自动跟随
        self._http_client = http_client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(
                connect=DEFAULT_DOWNLOAD_CONNECT_TIMEOUT,
                read=DEFAULT_DOWNLOAD_READ_TIMEOUT,
                write=10.0,
                pool=10.0,
            ),
            headers=DOWNLOAD_DEFAULT_HEADERS,
        )
        self._owns_http_client = http_client is None

        # ProgressReporter 与 Downloader
        self._progress_reporter = ProgressReporter(
            on_progress=on_progress or (lambda updates: None),
        )
        self._downloader = Downloader(
            progress_reporter=self._progress_reporter,
            http_client=self._http_client,
            semaphore=self._semaphore,
            conn=conn,
            video_parser=video_parser,
            cookie_repository=cookie_repository,
        )

        # 内部状态
        self._queue: asyncio.Queue[TaskItem | None] = asyncio.Queue()
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._running = False

    # === 生命周期 ===

    async def start(self) -> None:
        """启动调度循环与 ProgressReporter 汇报协程。"""
        if self._running:
            return
        self._running = True
        self._progress_reporter.start()
        self._loop_task = asyncio.create_task(self._schedule_loop())
        logger.info("调度器已启动，并发数=%d", self._max_concurrent)

    async def stop(self) -> None:
        """停止调度，等待进行中任务完成或取消，停止 ProgressReporter。"""
        if not self._running:
            return
        self._running = False
        # 向队列放入哨兵值停止调度循环
        await self._queue.put(None)
        if self._loop_task is not None:
            await self._loop_task
            self._loop_task = None
        # 取消所有进行中的下载任务
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        # 停止进度汇报
        await self._progress_reporter.stop()
        # 关闭内部创建的 httpx 客户端
        if self._owns_http_client:
            await self._http_client.aclose()
        logger.info("调度器已停止")

    # === 队列管理 ===

    def add_task_items(self, items: list[TaskItem]) -> None:
        """添加待下载项到内部队列。

        入队前执行去重检查：已存在 ``completed`` 记录的 aweme_id 跳过（设计文档 5.6 节）。

        Args:
            items: 待下载任务项列表
        """
        # 收集涉及的任务 ID 用于同步父任务展示统计（如 retry 重置状态后）
        task_ids: set[int] = set()
        for item in items:
            if item.aweme_id is not None and self._is_already_completed(item.aweme_id):
                logger.info("跳过已完成项 aweme_id=%s", item.aweme_id)
                continue
            self._queue.put_nowait(item)
            logger.info("入队 task_item id=%s aweme_id=%s", item.id, item.aweme_id)
            if item.task_id is not None:
                task_ids.add(item.task_id)
        for tid in task_ids:
            self._sync_task_stats(tid)

    def _is_already_completed(self, aweme_id: str) -> bool:
        """去重：查 task_items 是否已有该 aweme_id 的 completed 记录。

        Args:
            aweme_id: 抖音作品 ID

        Returns:
            已存在 completed 记录返回 True
        """
        item = self._item_repo.get_by_aweme_id(aweme_id)
        return item is not None and item.status == "completed"

    # === 调度循环 ===

    async def _schedule_loop(self) -> None:
        """调度主循环：从队列取任务项，创建 asyncio.Task 执行下载。"""
        while self._running:
            task_item = await self._queue.get()
            if task_item is None:
                # 哨兵值：stop() 发出的停止信号
                break
            if task_item.id is None:
                logger.warning("task_item id 为 None，跳过")
                continue
            task = asyncio.create_task(self._run_download(task_item))
            self._tasks[task_item.id] = task
            task.add_done_callback(lambda t, tid=task_item.id: self._tasks.pop(tid, None))

    def _sync_task_stats(self, task_id: int) -> None:
        """同步父任务的展示统计，不修改任何 task_item 状态。"""
        items = self._item_repo.get_by_task(task_id)
        if not items:
            return

        completed_count = sum(1 for item in items if item.status == "completed")
        failed_count = sum(1 for item in items if item.status == "failed")
        active_count = sum(
            1 for item in items if item.status in ("pending", "downloading", "paused")
        )

        self._task_repo.update_progress(
            task_id,
            completed_items=completed_count,
            total_items=len(items),
        )

        if completed_count == len(items):
            self._task_repo.update_status(task_id, "completed")
        elif active_count == 0 and failed_count > 0:
            self._task_repo.update_status(task_id, "failed")
        elif active_count > 0:
            self._task_repo.update_status(task_id, "downloading")

    async def _run_download(self, task_item: TaskItem) -> None:
        """单个任务项下载执行器。

        调用 ``downloader.download()``，根据结果触发回调。
        信号量由 Downloader 内部 acquire/release，此处不重复。

        Args:
            task_item: 待下载任务项
        """
        try:
            result = await self._downloader.download(task_item)
            if result.success:
                logger.info("task_item id=%s 下载成功", task_item.id)
                self._sync_task_stats(task_item.task_id)
                if self._on_item_completed is not None:
                    self._on_item_completed(task_item.id)
            else:
                reason = result.error or "未知错误"
                logger.warning("task_item id=%s 下载失败: %s", task_item.id, reason)
                self._sync_task_stats(task_item.task_id)
                if self._on_item_failed is not None:
                    self._on_item_failed(task_item.id, reason)
        except asyncio.CancelledError:
            # 由 pause() 触发的取消，status 已由 pause() 设置为 paused
            logger.info("task_item id=%s 下载被取消（暂停）", task_item.id)
            self._sync_task_stats(task_item.task_id)
            raise
        except Exception as e:
            logger.exception("task_item id=%s 下载异常", task_item.id)
            self._item_repo.update_status(task_item.id, "failed", fail_reason=str(e))
            self._sync_task_stats(task_item.task_id)
            if self._on_item_failed is not None:
                self._on_item_failed(task_item.id, str(e))

    # === 并发数动态调整 ===

    def set_max_concurrent(self, max_concurrent: int) -> None:
        """动态调整并发数。

        clamp 到 [1, 10]，重建 Semaphore。已运行的下载不受影响（它们持有旧 Semaphore）。

        Args:
            max_concurrent: 新的最大并发数
        """
        new_value = max(1, min(max_concurrent, MAX_CONCURRENT_LIMIT))
        if new_value == self._max_concurrent:
            return
        self._max_concurrent = new_value
        self._semaphore = asyncio.Semaphore(new_value)
        self._downloader._semaphore = self._semaphore
        logger.info("并发数调整为 %d", new_value)

    # === 暂停/恢复（设计文档 5.4 节）===

    async def pause(self, task_item_id: int) -> None:
        """暂停指定任务项。

        取消对应的 ``asyncio.Task``（触发 ``CancelledError``），
        Downloader 内部持久化进度后重抛，调度器将 status 置为 ``paused``。

        Args:
            task_item_id: 任务项 ID
        """
        task = self._tasks.get(task_item_id)
        task_finished = False
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            self._tasks.pop(task_item_id, None)
            task_finished = True

        # 只在任务仍在 downloading/processing 状态时才写 paused，
        # 避免在任务恰好完成时覆盖 "completed" 状态
        item = self._item_repo.get(task_item_id)
        if item is not None and item.status in ("downloading", "processing"):
            self._item_repo.update_status(task_item_id, "paused")
        elif task_finished:
            logger.info("暂停时 task_item id=%s 已完成，跳过状态覆盖", task_item_id)

        # 同步父任务展示统计
        if item is not None:
            self._sync_task_stats(item.task_id)
        logger.info("已暂停 task_item id=%s", task_item_id)

    async def resume(self, task_item_id: int) -> None:
        """恢复指定任务项。

        从 ``paused`` → 重新创建 ``asyncio.Task``，
        Downloader 检测 ``.part`` 文件后走 Range 续传。

        Args:
            task_item_id: 任务项 ID
        """
        item = self._item_repo.get(task_item_id)
        if item is None:
            logger.warning("恢复失败：task_item id=%s 不存在", task_item_id)
            return
        if item.status != "paused":
            logger.warning(
                "恢复失败：task_item id=%s 状态为 %s（非 paused）",
                task_item_id,
                item.status,
            )
            return
        self._item_repo.update_status(task_item_id, "downloading")
        self._sync_task_stats(item.task_id)
        task = asyncio.create_task(self._run_download(item))
        self._tasks[task_item_id] = task
        task.add_done_callback(lambda t, tid=task_item_id: self._tasks.pop(tid, None))
        logger.info("已恢复 task_item id=%s", task_item_id)

    async def pause_all(self) -> None:
        """暂停所有进行中的下载任务。"""
        ids = list(self._tasks.keys())
        for tid in ids:
            await self.pause(tid)
        logger.info("已暂停全部 %d 个任务", len(ids))

    async def resume_all(self) -> None:
        """恢复所有 paused 状态的任务项。"""
        paused_items = self._item_repo.get_by_status("paused")
        for item in paused_items:
            if item.id is not None and item.id not in self._tasks:
                await self.resume(item.id)
        logger.info("已恢复 %d 个 paused 任务", len(paused_items))

    # === 启动恢复（设计文档 4.2 节）===

    async def restore_pending_tasks(self) -> None:
        """应用启动时恢复未完成的下载任务。

        流程（设计文档 4.2 节第 1 点）：
        1. 将所有 ``downloading`` 状态重置为 ``paused``（上次中断了）
        2. 查询所有 ``pending`` 和 ``paused`` 的任务项
        3. 加入待下载队列（``paused`` 项恢复时走 Range 续传）
        """
        reset_count = self._item_repo.reset_downloading_to_paused()
        if reset_count > 0:
            logger.info("启动恢复：将 %d 个 downloading 重置为 paused", reset_count)
        pending = self._item_repo.get_by_status("pending")
        paused = self._item_repo.get_by_status("paused")
        items = pending + paused
        if items:
            # 对涉及的任务同步父任务展示统计
            tasks_seen: set[int] = set()
            for it in items:
                if it.task_id not in tasks_seen:
                    self._sync_task_stats(it.task_id)
                    tasks_seen.add(it.task_id)
            self.add_task_items(items)
            logger.info(
                "启动恢复：加入队列 %d 项（pending=%d, paused=%d）",
                len(items),
                len(pending),
                len(paused),
            )
