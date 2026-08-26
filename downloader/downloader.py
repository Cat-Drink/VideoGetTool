"""单项下载器模块。

实现单个 ``TaskItem`` 的下载逻辑，包括 httpx Range 请求、流式写入、
失败重试、图集并发、取消处理。严格遵循设计文档 5.2 节（下载流程）
与 5.3 节（重试策略）。

下载流程（设计文档 5.2 节）：
1. 从 SQLite 取 task_item，置为 downloading
2. 检查 .part 文件 → 读取已下载字节数（断点续传）
3. httpx Range 请求
4. 流式接收 64KB 块 → 追加写入 .part → 每 5s/1MB 持久化 → 更新进度
5. 完成 → .part 重命名为最终文件 → status=completed

重试策略（设计文档 5.3 节）：
- 网络异常 / 5xx / 461 / 412 → 重试，2^retry_count 秒指数退避
- 3 次上限 → status=failed
- 4xx（非限流）→ 直接失败不重试
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from app.logger import get_logger
from app.models import TaskItem, now_iso
from app.repositories import TaskItemRepository, TaskRepository
from downloader.constants import (
    LARGE_FILE_THRESHOLD,
    MAX_FILENAME_BASE_LENGTH,
    MAX_SEGMENTS,
    SEGMENT_SIZE,
)
from downloader.progress_reporter import ProgressReporter

if TYPE_CHECKING:
    from app.repositories import CookieRepository
    from crawlers.video_parser import VideoParser

logger = get_logger(__name__)

# === 常量（设计文档 5.2 / 5.3 节）===

# 流式接收块大小 64KB
CHUNK_SIZE: int = 64 * 1024

# 进度持久化间隔 5 秒
PERSIST_INTERVAL_SECONDS: int = 5

# 进度持久化间隔 1MB
PERSIST_INTERVAL_BYTES: int = 1024 * 1024

# 最大重试次数 3
MAX_RETRY_COUNT: int = 3

# 指数退避底数，等待 2^retry_count 秒
RETRY_BACKOFF_BASE: int = 2

# 风控限流状态码（与爬虫层一致，触发重试）
RATE_LIMITED_STATUS_CODES: frozenset[int] = frozenset({461, 412})

# v0.1.3：分片下载常量（SEGMENT_SIZE / MAX_SEGMENTS / LARGE_FILE_THRESHOLD）
# 已移至 downloader/constants.py 集中定义，本模块通过 import 复用


@dataclass(frozen=True)
class DownloadResult:
    """单项下载结果。

    Attributes:
        success: 是否下载成功
        local_path: 成功时的本地文件路径，失败为 None
        error: 失败原因，成功为 None
    """

    success: bool
    local_path: str | None = None
    error: str | None = None


def _select_urls_by_indices(urls: list[str], selected_indices_str: str) -> list[str]:
    """按 selected_image_indices JSON 字符串筛选 url 列表。

    语义与 ``worker.download_bridge._filter_image_urls`` 一致；
    在 downloader 内复制以避免 downloader→worker 循环依赖。

    Args:
        urls: 全量 url 列表
        selected_indices_str: 勾选索引 JSON 数组字符串；
            空字符串表示全选；非法 JSON 按全选处理

    Returns:
        筛选后的 url 列表
    """
    if not selected_indices_str:
        return list(urls)
    try:
        indices = json.loads(selected_indices_str)
    except (json.JSONDecodeError, TypeError):
        return list(urls)
    if not isinstance(indices, list):
        return list(urls)
    return [urls[i] for i in indices if isinstance(i, int) and 0 <= i < len(urls)]


class Downloader:
    """单项下载器。

    通过 httpx Range 请求流式下载文件，支持断点续传、失败重试、图集并发。
    进度通过 ProgressReporter 节流上报，状态持久化到 SQLite。

    注意：Downloader **不**修改 status 为 paused（归 Scheduler），
    仅在下载完成时置 completed、失败时置 failed。
    """

    def __init__(
        self,
        progress_reporter: ProgressReporter,
        http_client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        conn: sqlite3.Connection,
        video_parser: VideoParser | None = None,
        cookie_repository: CookieRepository | None = None,
        ffmpeg_path: str | None = None,
    ) -> None:
        """初始化下载器。

        Args:
            progress_reporter: 进度节流器
            http_client: httpx 异步客户端
            semaphore: 并发信号量（图集子任务也受此约束）
            conn: SQLite 连接（用于状态持久化与 download_dir 查询）
            video_parser: 图集直链失效时用于重新解析（v0.1.7 plan 6.6）；
                为 None 时图集 4xx 直接失败不重新解析
            cookie_repository: 重新解析时取有效 Cookie（v0.1.7 plan 6.6）；
                为 None 时图集 4xx 直接失败不重新解析
            ffmpeg_path: ffmpeg 可执行文件路径（B 站 DASH 合并用）；
                为 None 时自动查找（resources/ffmpeg/ 或系统 PATH）。
        """
        self._progress_reporter = progress_reporter
        self._http_client = http_client
        self._semaphore = semaphore
        self._conn = conn
        self._item_repo = TaskItemRepository(conn)
        self._task_repo = TaskRepository(conn)
        self._video_parser = video_parser
        self._cookie_repository = cookie_repository
        self._ffmpeg_path = ffmpeg_path
        # 按目标文件路径的并发锁：防止同名目标（同一视频/图集被多次下载）
        # 并发写同一个 .part 文件导致合并阶段文件占用冲突（WinError 32）
        self._file_locks: dict[str, asyncio.Lock] = {}

    def set_semaphore(self, semaphore: asyncio.Semaphore) -> None:
        """设置并发信号量（由 Scheduler 在并发数调整时调用）。"""
        self._semaphore = semaphore

    # === 路径推导 ===

    def _get_download_dir(self, task_item: TaskItem) -> Path:
        """查询 task_item 所属 task 的 download_dir。

        Args:
            task_item: 任务项

        Returns:
            下载目录 Path

        Raises:
            ValueError: task 不存在或 download_dir 为空
        """
        task = self._task_repo.get(task_item.task_id)
        if task is None or not task.download_dir:
            raise ValueError(f"task_id={task_item.task_id} 的 download_dir 为空或 task 不存在")
        return Path(task.download_dir)

    def _get_final_path(
        self,
        task_item: TaskItem,
        url: str,
        index: int | None = None,
        item_subtype: str | None = None,
    ) -> Path:
        """推导最终文件路径。

        命名规范（问题归档 #4）：采用"作者名 + 源媒体标题"截取前若干字
        作为本地文件名。

        - video / long_video: ``{download_dir}/{基础名}.{ext}``
        - image_set: ``{download_dir}/{基础名}/{基础名}-{index}.{ext}``

        Args:
            task_item: 任务项
            url: 下载直链（用于提取扩展名）
            index: 图集图片序号（从 1 开始），仅 image_set 使用
            item_subtype: 图集子项类型（'image' 静态图片 / 'video' 动图视频）

        Returns:
            最终文件路径
        """
        download_dir = self._get_download_dir(task_item)
        ext = self._extract_extension(url, task_item.type, item_subtype)
        base_name = self._build_base_name(task_item)
        if task_item.type == "image_set" and index is not None:
            target_dir = download_dir / base_name
            return target_dir / f"{base_name}-{index}{ext}"
        return download_dir / f"{base_name}{ext}"

    def _build_base_name(self, task_item: TaskItem) -> str:
        """构建本地文件基础名：作者名 + 源媒体标题。

        - 清洗 Windows 非法字符（``<>:"/\\|?*`` 及控制字符）
        - 截取前 ``MAX_FILENAME_BASE_LENGTH`` 字
        - 无作者/标题时回退到 ``aweme_id`` / ``item_{id}``

        Args:
            task_item: 任务项

        Returns:
            清洗截断后的基础名
        """
        raw = f"{task_item.author or ''} - {task_item.title or ''}".strip(" -").strip()
        if not raw:
            return task_item.aweme_id or f"item_{task_item.id}"
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw)
        cleaned = cleaned.rstrip(" .").strip()
        return cleaned[:MAX_FILENAME_BASE_LENGTH] or task_item.aweme_id or f"item_{task_item.id}"

    def _get_part_path(self, final_path: Path) -> Path:
        """推导 .part 临时文件路径。

        在最终文件名后追加 ``.part`` 后缀。

        Args:
            final_path: 最终文件路径

        Returns:
            .part 临时文件路径
        """
        return Path(str(final_path) + ".part")

    @staticmethod
    def _extract_extension(url: str, item_type: str, item_subtype: str | None = None) -> str:
        """从 URL 提取文件扩展名。

        从 URL path 部分提取扩展名，无法识别时按类型给默认值。

        Args:
            url: 下载直链
            item_type: 任务项类型（video / image_set / long_video）
            item_subtype: 图集子项类型（'image' 静态图片 / 'video' 动图视频）

        Returns:
            文件扩展名（含点号，如 ``.mp4``）
        """
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix and len(suffix) <= 5:
            return suffix
        # 默认扩展名
        if item_type == "image_set" and item_subtype != "video":
            return ".jpg"
        return ".mp4"

    # === 状态持久化 ===

    def _persist_progress(
        self,
        task_item_id: int,
        downloaded_bytes: int,
        total_bytes: int,
    ) -> None:
        """持久化下载进度到 SQLite。

        更新 ``task_items.downloaded_bytes``、``total_bytes``、``updated_at``。

        Args:
            task_item_id: 任务项 ID
            downloaded_bytes: 已下载字节数
            total_bytes: 文件总字节数
        """
        self._item_repo.update_bytes(task_item_id, downloaded_bytes, total_bytes)

    def _mark_status(
        self,
        task_item_id: int,
        status: str,
        fail_reason: str | None = None,
        local_path: str | None = None,
    ) -> None:
        """更新 task_items 状态及关联字段。

        Args:
            task_item_id: 任务项 ID
            status: 新状态
            fail_reason: 失败原因（仅 failed 时使用）
            local_path: 本地文件路径（仅 completed 时使用）
        """
        now = now_iso()
        with self._conn:
            if fail_reason is not None and local_path is not None:
                self._conn.execute(
                    "UPDATE task_items SET status=?, fail_reason=?, "
                    "local_path=?, updated_at=? WHERE id=?",
                    (status, fail_reason, local_path, now, task_item_id),
                )
            elif fail_reason is not None:
                self._conn.execute(
                    "UPDATE task_items SET status=?, fail_reason=?, updated_at=? WHERE id=?",
                    (status, fail_reason, now, task_item_id),
                )
            elif local_path is not None:
                self._conn.execute(
                    "UPDATE task_items SET status=?, local_path=?, updated_at=? WHERE id=?",
                    (status, local_path, now, task_item_id),
                )
            else:
                self._conn.execute(
                    "UPDATE task_items SET status=?, updated_at=? WHERE id=?",
                    (status, now, task_item_id),
                )

    # === 重试判断 ===

    def _should_retry(self, status_code: int | None, exception: Exception | None) -> bool:
        """判断是否应重试（设计文档 5.3 节）。

        - 网络异常（httpx.HTTPError 子类）→ True
        - HTTP 5xx → True
        - HTTP 461 / 412（风控限流）→ True
        - HTTP 4xx（非 461/412）→ False
        - HTTP 200/206 → 不进入重试逻辑（调用方保证）

        Args:
            status_code: HTTP 状态码，网络异常时为 None
            exception: 捕获的异常，HTTP 状态码错误时为 None

        Returns:
            是否应重试
        """
        if exception is not None:
            # httpx 网络异常（ConnectError、ReadTimeout、PoolTimeout 等）
            return isinstance(exception, httpx.HTTPError)
        if status_code is not None:
            if 500 <= status_code <= 599:
                return True
            if status_code in RATE_LIMITED_STATUS_CODES:
                return True
            if 400 <= status_code <= 499:
                return False
        return False

    async def _retry_with_backoff(self, retry_count: int) -> None:
        """指数退避等待 ``2^retry_count`` 秒（2s/4s/8s）。

        Args:
            retry_count: 当前重试次数（从 1 开始）
        """
        wait_seconds = RETRY_BACKOFF_BASE**retry_count
        logger.info("等待 %d 秒后重试（第 %d 次）", wait_seconds, retry_count)
        await asyncio.sleep(wait_seconds)

    def _finalize_file(self, part_path: Path, final_path: Path) -> str:
        """将 .part 文件重命名为最终文件名。

        若最终文件已存在则先删除（覆盖旧文件）。

        Args:
            part_path: .part 临时文件路径
            final_path: 最终文件路径

        Returns:
            规范化后的最终文件绝对路径字符串
        """
        if final_path.exists():
            final_path.unlink()
        part_path.rename(final_path)
        # 规范化路径：转换为绝对路径并统一正斜杠，解决 Windows 路径问题
        return os.path.normpath(os.path.abspath(str(final_path)))

    # === 分片下载 ===

    @staticmethod
    def _is_bilibili_item(task_item: TaskItem) -> bool:
        """判断任务项是否为 B 站下载（存在 bvid 或 DASH 音频流地址）。

        B 站 CDN 要求 Referer 为 https://www.bilibili.com/，
        与抖音 CDN（https://www.douyin.com/）不同，需区分请求头。

        Args:
            task_item: 任务项

        Returns:
            B 站任务项返回 True
        """
        return bool(task_item.bvid or task_item.audio_url)

    def _get_download_headers(self, task_item: TaskItem) -> dict[str, str]:
        """按任务项来源构造下载请求头（含 Referer）。

        B 站 CDN 使用 bilibili.com Referer，其余（抖音等）使用默认头。
        默认头来自 Scheduler 注入的 httpx 客户端（抖音 Referer）。

        Args:
            task_item: 任务项

        Returns:
            附加请求头字典
        """
        if self._is_bilibili_item(task_item):
            return {"Referer": "https://www.bilibili.com/"}
        return {}

    async def _get_file_size(self, url: str, headers: dict[str, str] | None = None) -> int | None:
        """通过 HEAD 请求获取文件总大小。

        Args:
            url: 下载直链
            headers: 附加请求头（如 B 站 Referer）

        Returns:
            文件总字节数，获取失败返回 None
        """
        try:
            response = await self._http_client.head(url, headers=headers)
            if response.status_code == 200:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    return int(content_length)
        except httpx.HTTPError as e:
            logger.warning("HEAD 请求获取文件大小失败: %s", e)
        return None

    @staticmethod
    def _calculate_segments(total_bytes: int) -> list[tuple[int, int]]:
        """计算分片字节范围列表。

        segment_count = min(ceil(total_bytes / SEGMENT_SIZE), MAX_SEGMENTS)
        每个分片大小 = ceil(total_bytes / segment_count)

        Args:
            total_bytes: 文件总字节数

        Returns:
            (start, end) 字节范围列表，end 为包含的末字节偏移
        """
        segment_count = min(math.ceil(total_bytes / SEGMENT_SIZE), MAX_SEGMENTS)
        segment_size = math.ceil(total_bytes / segment_count)
        segments: list[tuple[int, int]] = []
        for i in range(segment_count):
            start = i * segment_size
            end = min(start + segment_size - 1, total_bytes - 1)
            segments.append((start, end))
        return segments

    def _merge_segments(self, part_paths: list[Path], final_path: Path) -> str:
        """将分片 .part.{i} 文件按序合并为最终文件。

        合并完成后删除所有临时分片文件。

        Args:
            part_paths: 分片文件路径列表（按序号排序）
            final_path: 最终文件路径

        Returns:
            规范化后的最终文件绝对路径字符串
        """
        if final_path.exists():
            final_path.unlink()
        with open(final_path, "wb") as out:
            for part_path in part_paths:
                with open(part_path, "rb") as part:
                    while True:
                        chunk = part.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        out.write(chunk)
        # 删除临时分片文件
        for part_path in part_paths:
            if part_path.exists():
                part_path.unlink()
        return os.path.normpath(os.path.abspath(str(final_path)))

    async def _download_segmented(
        self,
        task_item: TaskItem,
        url: str,
        final_path: Path,
        total_bytes: int,
        headers: dict[str, str] | None = None,
        report_progress: bool = True,
    ) -> DownloadResult:
        """分片并发下载大文件。

        将文件分割为多个字节范围段，使用独立的 HTTP Range 请求并发下载。
        所有分片完成后合并为最终文件。

        Args:
            task_item: 任务项
            url: 下载直链
            final_path: 最终文件路径
            total_bytes: 文件总字节数
            headers: 附加请求头（如 B 站 Referer）
            report_progress: 是否上报字节级进度（False 时仅持久化，
                不写入 ProgressReporter，避免覆盖外层更粗粒度的进度口径）

        Returns:
            下载结果
        """
        logger.info(
            "分片下载 task_item id=%s total_bytes=%d",
            task_item.id,
            total_bytes,
        )

        segments = self._calculate_segments(total_bytes)
        segment_count = len(segments)
        part_paths = [Path(str(final_path) + f".part.{i}") for i in range(segment_count)]
        segment_progress = [0] * segment_count

        # 进度聚合与持久化
        last_persist_time = time.monotonic()
        last_persist_bytes = 0

        def make_chunk_callback(idx: int) -> Callable[[int], None]:
            def callback(chunk_bytes: int) -> None:
                nonlocal last_persist_time, last_persist_bytes
                segment_progress[idx] += chunk_bytes
                total_downloaded = sum(segment_progress)
                if report_progress:
                    self._progress_reporter.update(task_item.id, total_downloaded, total_bytes)
                now = time.monotonic()
                if (
                    now - last_persist_time >= PERSIST_INTERVAL_SECONDS
                    or total_downloaded - last_persist_bytes >= PERSIST_INTERVAL_BYTES
                ):
                    self._persist_progress(task_item.id, total_downloaded, total_bytes)
                    last_persist_time = now
                    last_persist_bytes = total_downloaded

            return callback

        # 分片信号量（不挤占主下载并发槽位）
        segment_semaphore = asyncio.Semaphore(MAX_SEGMENTS)

        async def download_one_segment(
            idx: int,
            sem: asyncio.Semaphore,
        ) -> int:
            async with sem:
                start, end = segments[idx]
                return await self._download_segment(
                    url, part_paths[idx], start, end, make_chunk_callback(idx), headers=headers
                )

        try:
            results = await asyncio.gather(
                *[download_one_segment(i, segment_semaphore) for i in range(segment_count)],
                return_exceptions=True,
            )

            # 检查结果
            for i, result in enumerate(results):
                if isinstance(result, ValueError):
                    # 服务端不支持 byte-range，回退到单流下载
                    logger.warning(
                        "分片 %d 返回 200，回退到单流下载 task_item id=%s",
                        i,
                        task_item.id,
                    )
                    # 清理已下载的分片文件
                    for pp in part_paths:
                        if pp.exists():
                            pp.unlink()
                    return DownloadResult(
                        success=False,
                        error="FALLBACK_TO_SINGLE_STREAM",
                    )
                if isinstance(result, BaseException):
                    if isinstance(result, asyncio.CancelledError):
                        raise
                    reason = f"分片 {i} 下载失败: {result}"
                    self._mark_status(task_item.id, "failed", fail_reason=reason)
                    # 清理已下载的分片文件
                    for pp in part_paths:
                        if pp.exists():
                            pp.unlink()
                    return DownloadResult(success=False, error=reason)

            # 所有分片完成 → 合并
            final_str = self._merge_segments(part_paths, final_path)
            self._mark_status(task_item.id, "completed", local_path=final_str)
            # 最终持久化一次
            self._persist_progress(task_item.id, total_bytes, total_bytes)
            logger.info("分片下载完成 task_item id=%s path=%s", task_item.id, final_str)
            return DownloadResult(success=True, local_path=final_str)

        except asyncio.CancelledError:
            # 暂停/取消：持久化进度，保留 .part 文件
            total_downloaded = sum(segment_progress)
            self._persist_progress(task_item.id, total_downloaded, total_bytes)
            logger.info(
                "分片下载被取消 task_item id=%s 已保存进度 %d bytes",
                task_item.id,
                total_downloaded,
            )
            raise

    # === 下载主流程 ===

    async def download(self, task_item: TaskItem) -> DownloadResult:
        """单项下载主入口（设计文档 5.2 节）。

        根据 type 分发到单文件或图集下载流程。
        image_set 类型的 url 字段以换行符分隔多个图片 URL。

        Args:
            task_item: 待下载任务项

        Returns:
            下载结果
        """
        self._mark_status(task_item.id, "downloading")
        logger.info(
            "开始下载 task_item id=%s aweme_id=%s type=%s",
            task_item.id,
            task_item.aweme_id,
            task_item.type,
        )

        if task_item.type == "image_set":
            urls = [u.strip() for u in task_item.url.split("\n") if u.strip()]
            if not urls:
                self._mark_status(task_item.id, "failed", fail_reason="图集 URL 为空")
                return DownloadResult(success=False, error="图集 URL 为空")
            final_path = self._get_final_path(task_item, urls[0], index=1)
            target_dir = final_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            # 图集：按目标文件夹串行化，防止同名图集并发写冲突
            lock_key = str(target_dir)
            lock = self._file_locks.setdefault(lock_key, asyncio.Lock())
            async with lock:
                try:
                    return await self._download_image_set(task_item, urls, target_dir)
                finally:
                    self._file_locks.pop(lock_key, None)

        # v0.4.0：B 站 DASH 格式（音视频分离）→ 走 DASH 合并流程
        if task_item.audio_url:
            final_path = self._get_final_path(task_item, task_item.url)
            # DASH 流 URL 扩展名为 .m4s，最终合并输出强制为 .mp4
            if final_path.suffix.lower() == ".m4s":
                final_path = final_path.with_suffix(".mp4")
            final_path.parent.mkdir(parents=True, exist_ok=True)
            lock_key = str(final_path)
            lock = self._file_locks.setdefault(lock_key, asyncio.Lock())
            async with lock:
                try:
                    return await self._download_dash(task_item, final_path)
                finally:
                    self._file_locks.pop(lock_key, None)

        final_path = self._get_final_path(task_item, task_item.url)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        # 视频：按目标文件串行化，防止同名目标并发写 .part 冲突
        lock_key = str(final_path)
        lock = self._file_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            try:
                return await self._download_single_file(task_item, task_item.url, final_path)
            finally:
                self._file_locks.pop(lock_key, None)

    # === DASH 音视频合并（v0.4.0 B 站支持） ===

    def _find_ffmpeg(self) -> str | None:
        """定位 ffmpeg 可执行文件路径。

        查找顺序:
            1. 构造时注入的 ffmpeg_path
            2. 项目资源目录 resources/ffmpeg/ffmpeg.exe（打包随附）
            3. 系统 PATH（shutil.which）

        Returns:
            ffmpeg 可执行文件绝对路径；未找到返回 None。
        """
        if self._ffmpeg_path:
            return self._ffmpeg_path
        # 项目资源目录（开发与打包均可用相对位置解析）
        candidates = [
            Path("resources/ffmpeg/ffmpeg.exe"),
            Path(__file__).resolve().parent.parent / "resources" / "ffmpeg" / "ffmpeg.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c.resolve())
        return shutil.which("ffmpeg")

    async def _merge_dash_streams(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> None:
        """用 ffmpeg 将视频流与音频流合并为单 MP4（流拷贝，不重编码）。

        Args:
            video_path: 已下载的视频流文件
            audio_path: 已下载的音频流文件
            output_path: 合并输出文件路径

        Raises:
            RuntimeError: ffmpeg 未找到或合并失败。
        """
        ffmpeg = self._find_ffmpeg()
        if ffmpeg is None:
            raise RuntimeError("未找到 ffmpeg，无法合并 B 站 DASH 音视频流")
        # 先清理可能存在的旧输出
        if output_path.exists():
            output_path.unlink()
        proc = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c", "copy",
            "-f", "mp4",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg 合并失败（退出码 {proc.returncode}）: "
                f"{stderr.decode(errors='replace')[:500]}"
            )

    async def _download_dash(
        self,
        task_item: TaskItem,
        final_path: Path,
    ) -> DownloadResult:
        """下载 B 站 DASH 音视频流并用 ffmpeg 合并。

        流程:
            1. 并发下载视频流（task_item.url）与音频流（task_item.audio_url）
               到临时文件 {final_path}.video / {final_path}.audio
            2. ffmpeg -c copy 合并为最终 MP4
            3. 清理临时文件，标记任务项完成

        Args:
            task_item: 任务项（url=视频流, audio_url=音频流）
            final_path: 最终合并文件路径

        Returns:
            下载结果
        """
        video_part = Path(str(final_path) + ".video")
        audio_part = Path(str(final_path) + ".audio")

        # 清理可能存在的旧临时文件
        for tmp in (video_part, audio_part):
            if tmp.exists():
                tmp.unlink()

        try:
            # 并发下载两条流（不单独标记完成状态，由合并后统一标记）
            video_result, audio_result = await asyncio.gather(
                self._download_single_file(
                    task_item,
                    task_item.url,
                    video_part,
                    mark_status=False,
                    report_progress=True,
                ),
                self._download_single_file(
                    task_item,
                    task_item.audio_url,
                    audio_part,
                    mark_status=False,
                    report_progress=False,
                ),
                return_exceptions=True,
            )

            # 处理异常结果
            if isinstance(video_result, BaseException):
                if isinstance(video_result, asyncio.CancelledError):
                    raise
                raise RuntimeError(f"视频流下载失败: {video_result}")
            if isinstance(audio_result, BaseException):
                if isinstance(audio_result, asyncio.CancelledError):
                    raise
                raise RuntimeError(f"音频流下载失败: {audio_result}")
            if not video_result.success:
                self._mark_status(
                    task_item.id, "failed", fail_reason=video_result.error or "视频流下载失败"
                )
                return video_result
            if not audio_result.success:
                self._mark_status(
                    task_item.id, "failed", fail_reason=audio_result.error or "音频流下载失败"
                )
                return audio_result

            # 合并音视频
            await self._merge_dash_streams(video_part, audio_part, final_path)

        except asyncio.CancelledError:
            # 暂停/取消：清理临时文件后重抛（进度已由子下载持久化）
            for tmp in (video_part, audio_part):
                if tmp.exists():
                    tmp.unlink()
            raise
        except (httpx.HTTPError, OSError) as e:
            reason = f"DASH 下载失败: {e}"
            self._mark_status(task_item.id, "failed", fail_reason=reason)
            return DownloadResult(success=False, error=reason)
        except RuntimeError as e:
            reason = f"DASH 合并失败: {e}"
            self._mark_status(task_item.id, "failed", fail_reason=reason)
            return DownloadResult(success=False, error=reason)
        finally:
            # 清理临时流文件
            for tmp in (video_part, audio_part):
                if tmp.exists():
                    tmp.unlink()

        final_str = os.path.normpath(os.path.abspath(str(final_path)))
        self._mark_status(task_item.id, "completed", local_path=final_str)
        # 合并完成：统一上报 100% 进度，避免 UI 进度条停留在视频流下载进度
        self._progress_reporter.update(task_item.id, 100, 100, status="completed")
        logger.info("DASH 合并完成 task_item id=%s path=%s", task_item.id, final_str)
        return DownloadResult(success=True, local_path=final_str)

    async def _download_single_file(
        self,
        task_item: TaskItem,
        url: str,
        final_path: Path,
        mark_status: bool = True,
        report_progress: bool = True,
    ) -> DownloadResult:
        """单文件下载（视频/长视频/图集单张）。

        含 Range 续传、流式写入、重试。受总 Semaphore 约束。
        大文件（≥10MB）自动切换为分片并发下载。

        Args:
            task_item: 任务项
            url: 下载直链
            final_path: 最终文件路径
            mark_status: 是否在完成/失败时标记 task_items 状态。
                图集子下载设为 False，由 _download_image_set 统一标记。
            report_progress: 是否上报字节级进度。
                v0.1.7：图集子下载设为 False，由 _download_image_set
                按"M/N 张"粒度上报，避免字节进度覆盖张数进度。

        Returns:
            下载结果
        """
        part_path = self._get_part_path(final_path)
        retry_count = task_item.retry_count

        # 按来源区分请求头（B 站 CDN 需要 bilibili.com Referer）
        source_headers = self._get_download_headers(task_item)

        # 大文件分片下载探测
        file_size = await self._get_file_size(url, headers=source_headers or None)
        if file_size is not None and file_size >= LARGE_FILE_THRESHOLD and not part_path.exists():
            async with self._semaphore:
                result = await self._download_segmented(
                    task_item, url, final_path, file_size,
                    headers=source_headers or None,
                    report_progress=report_progress,
                )
            if result.success or result.error != "FALLBACK_TO_SINGLE_STREAM":
                return result
            # 回退到单流下载
            logger.info("回退到单流下载 task_item id=%s", task_item.id)

        async with self._semaphore:
            while True:
                # 检查 .part 文件是否存在 → 读取已下载字节数（断点续传）
                downloaded_bytes = part_path.stat().st_size if part_path.exists() else 0

                # 构造请求头（来源 Referer + Range）
                headers: dict[str, str] = dict(source_headers)
                if downloaded_bytes > 0:
                    headers["Range"] = f"bytes={downloaded_bytes}-"

                # 总字节数：断点续传已下载部分 + 本次 Content-Length
                # 在 try 外初始化，取消时简化为 0 兜底
                total_bytes = 0
                try:
                    async with self._http_client.stream("GET", url, headers=headers) as response:
                        # ISSUE-20 诊断：记录响应 Content-Type，识别 CDN 返回
                        # WebP 缩略图占位（本应返回 video_mp4 却给了 image/webp）
                        resp_content_type = response.headers.get("Content-Type", "").lower()
                        if "webp" in resp_content_type or "image" in resp_content_type:
                            logger.warning(
                                "下载响应为图片而非视频: url=%s content_type=%s status=%d",
                                url[:200],
                                resp_content_type,
                                response.status_code,
                            )
                        if response.status_code == 200:
                            # 服务端不支持 Range 或文件已变，从头下载
                            downloaded_bytes = 0
                        elif response.status_code == 206:
                            pass  # 续传成功
                        elif self._should_retry(response.status_code, None):
                            # 可重试错误（5xx / 461 / 412）
                            retry_count += 1
                            self._item_repo.update_retry(task_item.id, retry_count)
                            if retry_count > MAX_RETRY_COUNT:
                                reason = f"HTTP {response.status_code} 重试耗尽"
                                if mark_status:
                                    self._mark_status(task_item.id, "failed", fail_reason=reason)
                                return DownloadResult(success=False, error=reason)
                            logger.warning(
                                "HTTP %d，第 %d 次重试 task_item id=%s",
                                response.status_code,
                                retry_count,
                                task_item.id,
                            )
                            await self._retry_with_backoff(retry_count)
                            continue
                        else:
                            # 不可重试错误（4xx 非限流）
                            reason = f"HTTP {response.status_code}"
                            if mark_status:
                                self._mark_status(task_item.id, "failed", fail_reason=reason)
                            return DownloadResult(success=False, error=reason)

                        # 流式接收
                        try:
                            content_length = int(response.headers.get("Content-Length", 0))
                        except (ValueError, TypeError):
                            content_length = 0
                        total_bytes = downloaded_bytes + content_length
                        downloaded_bytes = await self._stream_to_file(
                            response,
                            part_path,
                            task_item,
                            downloaded_bytes,
                            total_bytes,
                            report_progress=report_progress,
                        )

                    # 下载完成 → 重命名 → 标记完成
                    final_str = self._finalize_file(part_path, final_path)
                    if mark_status:
                        self._mark_status(task_item.id, "completed", local_path=final_str)
                    logger.info("下载完成 task_item id=%s path=%s", task_item.id, final_str)
                    return DownloadResult(success=True, local_path=final_str)

                except asyncio.CancelledError:
                    # 暂停/取消：持久化进度，保留 .part 文件，不修改 status（归 Scheduler）
                    # _stream_to_file 可能已持久化更准确的值，此处读 .part 实际大小兜底
                    actual_bytes = part_path.stat().st_size if part_path.exists() else 0
                    self._persist_progress(task_item.id, actual_bytes, total_bytes)
                    logger.info(
                        "下载被取消 task_item id=%s 已保存进度 %d bytes",
                        task_item.id,
                        actual_bytes,
                    )
                    raise

                except httpx.HTTPError as e:
                    # 网络异常 → 重试
                    retry_count += 1
                    self._item_repo.update_retry(task_item.id, retry_count)
                    if retry_count > MAX_RETRY_COUNT:
                        reason = f"网络异常重试耗尽: {e}"
                        if mark_status:
                            self._mark_status(task_item.id, "failed", fail_reason=reason)
                        return DownloadResult(success=False, error=reason)
                    logger.warning(
                        "网络异常 %s，第 %d 次重试 task_item id=%s",
                        e,
                        retry_count,
                        task_item.id,
                    )
                    await self._retry_with_backoff(retry_count)
                    continue

    async def _stream_to_file(
        self,
        response: httpx.Response,
        part_path: Path,
        task_item: TaskItem,
        downloaded_bytes: int,
        total_bytes: int,
        report_progress: bool = True,
    ) -> int:
        """流式接收响应体写入 .part 文件。

        每块 64KB 追加写入、更新内存计数、每 5s/1MB 持久化、更新 ProgressReporter。
        捕获 CancelledError 时持久化进度后重抛。

        Args:
            response: httpx 流式响应
            part_path: .part 临时文件路径
            task_item: 任务项
            downloaded_bytes: 起始已下载字节数（断点续传）
            total_bytes: 文件总字节数
            report_progress: 是否上报字节级进度。
                v0.1.7：图集子下载传 False，避免覆盖 _download_image_set
                按"M/N 张"粒度上报的进度。

        Returns:
            最终已下载字节数
        """
        last_persist_time = time.monotonic()
        last_persist_bytes = downloaded_bytes
        # downloaded_bytes == 0 表示从头下载（新文件或服务端返回 200 不支持 Range）
        # → 用 "wb" 截断旧 .part 内容；否则 "ab" 续传追加。
        mode = "wb" if downloaded_bytes == 0 else "ab"

        try:
            with open(part_path, mode) as f:
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    f.write(chunk)
                    downloaded_bytes += len(chunk)
                    # 更新进度（节流器内部去重）
                    if report_progress:
                        self._progress_reporter.update(
                            task_item.id,
                            downloaded_bytes,
                            total_bytes,
                            status="downloading",
                        )
                    # 检查持久化条件：5 秒 或 1MB
                    now = time.monotonic()
                    if (
                        now - last_persist_time >= PERSIST_INTERVAL_SECONDS
                        or downloaded_bytes - last_persist_bytes >= PERSIST_INTERVAL_BYTES
                    ):
                        self._persist_progress(task_item.id, downloaded_bytes, total_bytes)
                        last_persist_time = now
                        last_persist_bytes = downloaded_bytes
        except asyncio.CancelledError:
            # 持久化进度后重抛（设计文档 5.4 节）
            self._persist_progress(task_item.id, downloaded_bytes, total_bytes)
            raise

        # 最终持久化一次
        self._persist_progress(task_item.id, downloaded_bytes, total_bytes)
        return downloaded_bytes

    async def _download_segment(
        self,
        url: str,
        part_path: Path,
        start: int,
        end: int,
        on_chunk: Callable[[int], None],
        headers: dict[str, str] | None = None,
    ) -> int:
        """下载单个分片到 .part.{index} 文件。

        含 Range 续传、流式写入、独立重试。

        Args:
            url: 下载直链
            part_path: 分片临时文件路径（.part.{index}）
            start: 分片起始字节（包含）
            end: 分片结束字节（包含）
            on_chunk: 每接收一个数据块的回调，参数为本块字节数
            headers: 附加请求头（如 B 站 Referer）

        Returns:
            该分片已下载的总字节数

        Raises:
            ValueError: 服务端返回 200 而非 206（不支持 byte-range）
            httpx.HTTPError: 重试耗尽后的网络异常
        """
        retry_count = 0

        while True:
            # 检查 .part 文件是否存在 → 读取已下载字节数（断点续传）
            downloaded = part_path.stat().st_size if part_path.exists() else 0
            segment_start = start + downloaded

            headers = dict(headers or {})
            if downloaded > 0:
                headers["Range"] = f"bytes={segment_start}-{end}"
            else:
                headers["Range"] = f"bytes={start}-{end}"

            try:
                async with self._http_client.stream("GET", url, headers=headers) as response:
                    if response.status_code == 200:
                        # 服务端不支持 byte-range，无法分片下载
                        raise ValueError("服务端返回 200 而非 206，不支持 byte-range 分片下载")
                    elif response.status_code == 206:
                        pass  # 分片请求成功
                    elif self._should_retry(response.status_code, None):
                        retry_count += 1
                        if retry_count > MAX_RETRY_COUNT:
                            raise httpx.HTTPError(f"HTTP {response.status_code} 重试耗尽")
                        logger.warning(
                            "分片 HTTP %d，第 %d 次重试",
                            response.status_code,
                            retry_count,
                        )
                        await self._retry_with_backoff(retry_count)
                        continue
                    else:
                        raise httpx.HTTPError(f"HTTP {response.status_code}")

                    # 流式接收
                    mode = "ab" if downloaded > 0 else "wb"
                    with open(part_path, mode) as f:
                        async for chunk in response.aiter_bytes(CHUNK_SIZE):
                            f.write(chunk)
                            downloaded += len(chunk)
                            on_chunk(len(chunk))

                return downloaded

            except asyncio.CancelledError:
                raise
            except ValueError:
                raise
            except httpx.HTTPError as e:
                retry_count += 1
                if retry_count > MAX_RETRY_COUNT:
                    raise
                logger.warning(
                    "分片网络异常 %s，第 %d 次重试",
                    e,
                    retry_count,
                )
                await self._retry_with_backoff(retry_count)
                continue

    # === 图集直链失效重新解析（v0.1.7 plan 6.6）===

    def _is_link_expired(self, error: str | None) -> bool:
        """判断下载失败原因是否为图片直链失效（403/404）。

        Args:
            error: ``DownloadResult.error`` 字符串

        Returns:
            失效返回 True（可重新解析），其他错误返回 False
        """
        if not error:
            return False
        return "HTTP 403" in error or "HTTP 404" in error

    @staticmethod
    def _get_item_subtype(task_item: TaskItem, idx: int) -> str | None:
        """获取图集指定索引的子项媒体类型。

        从 ``task_item.item_types`` JSON 数组中解析第 idx 项的类型。
        无 item_types 数据时返回 None（表示按默认类型处理）。

        Args:
            task_item: 任务项
            idx: 0-based 索引

        Returns:
            'image' 或 'video'；无法确定时返回 None
        """
        if not task_item.item_types:
            return None
        try:
            types = json.loads(task_item.item_types)
            if isinstance(types, list) and 0 <= idx < len(types):
                return types[idx]
        except (json.JSONDecodeError, IndexError):
            pass
        return None

    def _can_reparse(self) -> bool:
        """是否具备图片直链重新解析能力。

        需要 ``video_parser`` 和 ``cookie_repository`` 同时注入。
        """
        return self._video_parser is not None and self._cookie_repository is not None

    def _get_cookie_string(self) -> str | None:
        """从 Cookie 池取一个有效 Cookie 字符串。

        Returns:
            Cookie ``content`` 字符串；无可用 Cookie 返回 None
        """
        if self._cookie_repository is None:
            return None
        cookie = self._cookie_repository.get_valid()
        return cookie.content if cookie else None

    async def _reparse_single_image_url(
        self,
        task_item: TaskItem,
        idx: int,
    ) -> str | None:
        """图片直链失效时重新解析，返回指定索引的新 url。

        按 plan 6.6：调用 ``VideoParser.parse_video`` 重新获取全量 image_urls，
        再按 ``task_item.selected_image_indices`` 重新筛选，取第 idx 个。
        重新解析失败返回 None（由调用方按原失败结果处理）。

        Args:
            task_item: 任务项
            idx: 在已筛选子集中的 0-based 索引

        Returns:
            新的图片直链；无法重新解析返回 None
        """
        if not self._can_reparse():
            return None
        if task_item.aweme_id is None:
            logger.warning(
                "aweme_id 为空，无法重新解析 task_item id=%s",
                task_item.id,
            )
            return None
        cookie = self._get_cookie_string()
        if cookie is None:
            logger.warning(
                "无可用 Cookie，无法重新解析 task_item id=%s",
                task_item.id,
            )
            return None
        try:
            video_info = await self._video_parser.parse_video(task_item.aweme_id, cookie)
        except Exception as e:
            logger.warning(
                "图片直链重新解析失败 task_item id=%s: %s",
                task_item.id,
                e,
            )
            return None
        # v0.2.x：使用 merged_item_urls 确保动图视频直链被保留
        new_all_urls = list(video_info.merged_item_urls or [])
        new_selected = _select_urls_by_indices(new_all_urls, task_item.selected_image_indices)
        if 0 <= idx < len(new_selected):
            return new_selected[idx]
        logger.warning(
            "重新解析后索引 %d 越界（共 %d 张）task_item id=%s",
            idx,
            len(new_selected),
            task_item.id,
        )
        return None

    async def _download_image_set(
        self,
        task_item: TaskItem,
        urls: list[str],
        target_dir: Path,
    ) -> DownloadResult:
        """图集并发下载（设计文档 5.2 节 + 2.4 节）。

        对每个 URL 创建 _download_single_file 子任务，asyncio.gather 并发执行。
        每个子任务受总 Semaphore 约束。任一失败 → 整个图集标记 failed。

        v0.1.7：子下载设 ``report_progress=False``，由本方法按"M/N 张"粒度
        上报进度，避免字节级进度覆盖张数进度。每张图片子下载完成时调用
        ``progress_reporter.update(task_item.id, 已下载张数, 总张数)``，
        UI 端 ``TaskItemWidget`` 据此显示"已下载 M/N 张"。

        Args:
            task_item: 任务项
            urls: 图片直链列表
            target_dir: 图集目标目录

        Returns:
            下载结果（成功时 local_path 为目录路径）
        """
        logger.info(
            "图集下载 task_item id=%s 共 %d 张图片",
            task_item.id,
            len(urls),
        )
        total_images = len(urls)
        # 初始进度：0 张已完成
        self._progress_reporter.update(task_item.id, 0, total_images)

        # 已完成图片数计数器与锁（gather 并发完成回调需同步）
        completed_count = 0
        completed_lock = asyncio.Lock()

        async def _download_one(seq: int, url: str) -> DownloadResult:
            nonlocal completed_count
            # v0.2.x：逐项媒体类型（动图项存为视频，其余存为图片）
            item_subtype = self._get_item_subtype(task_item, seq - 1)
            final_path = self._get_final_path(task_item, url, index=seq, item_subtype=item_subtype)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            result = await self._download_single_file(
                task_item,
                url,
                final_path,
                mark_status=False,
                report_progress=False,
            )
            # 图片直链失效重新解析（v0.1.7 plan 6.6）
            if not result.success and self._is_link_expired(result.error):
                # seq 为 1-based 序号，转 0-based 索引取重新解析后的 url
                new_url = await self._reparse_single_image_url(task_item, seq - 1)
                if new_url is not None:
                    logger.info(
                        "图片 %d 直链失效，重新解析后重试 task_item id=%s",
                        seq,
                        task_item.id,
                    )
                    result = await self._download_single_file(
                        task_item,
                        new_url,
                        final_path,
                        mark_status=False,
                        report_progress=False,
                    )
            if result.success:
                async with completed_lock:
                    completed_count += 1
                    self._progress_reporter.update(
                        task_item.id,
                        completed_count,
                        total_images,
                    )
            return result

        tasks: list = [_download_one(i, url) for i, url in enumerate(urls, 1)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 检查结果：任一失败 → 整个图集失败
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                if not isinstance(result, asyncio.CancelledError):
                    reason = f"图片 {i + 1} 下载异常: {result}"
                    self._mark_status(task_item.id, "failed", fail_reason=reason)
                    return DownloadResult(success=False, error=reason)
                raise result
            if not result.success:
                reason = f"图片 {i + 1} 下载失败: {result.error}"
                self._mark_status(task_item.id, "failed", fail_reason=reason)
                return DownloadResult(success=False, error=reason)

        # 全部成功
        local_path = os.path.normpath(os.path.abspath(str(target_dir)))
        self._mark_status(task_item.id, "completed", local_path=local_path)
        logger.info("图集下载完成 task_item id=%s path=%s", task_item.id, local_path)
        return DownloadResult(success=True, local_path=local_path)
