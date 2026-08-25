"""B 站 DASH 音视频合并下载测试。

覆盖：
    - _find_ffmpeg 的查找策略（注入路径优先 / 无注入时回退）
    - _download_dash 的成功合并流程（mock 子下载与 ffmpeg）
    - DASH 视频流下载失败时的错误处理
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.database import get_memory_connection
from app.models import Task, TaskItem
from app.repositories import TaskItemRepository, TaskRepository
from downloader.downloader import Downloader, DownloadResult
from downloader.progress_reporter import ProgressReporter

pytestmark = pytest.mark.bilibili


# === 辅助函数 ===


def _make_downloader(
    conn: object = None,
    ffmpeg_path: str | None = "C:/ffmpeg/ffmpeg.exe",
) -> Downloader:
    """创建测试用 Downloader。"""
    if conn is None:
        conn = get_memory_connection()
    reporter = MagicMock(spec=ProgressReporter)
    http_client = httpx.AsyncClient()
    semaphore = asyncio.Semaphore(10)
    return Downloader(
        reporter,
        http_client,
        semaphore,
        conn,  # type: ignore[arg-type]
        ffmpeg_path=ffmpeg_path,
    )


def _make_dash_item(download_dir: str = "/tmp/test_dash") -> tuple[Downloader, TaskItem]:
    """创建带 audio_url 的 DASH 任务项并插入数据库。"""
    conn = get_memory_connection()
    task_repo = TaskRepository(conn)
    task_id = task_repo.create(
        Task(
            id=None,
            source_type="single",
            source_url="https://www.bilibili.com/video/BV1xx",
            status="pending",
            total_items=1,
            download_dir=download_dir,
        )
    )
    item_repo = TaskItemRepository(conn)
    item_id = item_repo.create(
        TaskItem(
            id=None,
            task_id=task_id,
            aweme_id="BV1xx",
            bvid="BV1xx",
            url="https://cdn.example.com/video.m4s",
            audio_url="https://cdn.example.com/audio.m4s",
            type="video",
            title="测试视频",
            author="测试作者",
            status="pending",
            dash_merged="",
        )
    )
    dl = _make_downloader(conn=conn)
    item = item_repo.get(item_id)
    assert item is not None
    return dl, item


# === 测试 ===


class TestFindFfmpeg:
    """_find_ffmpeg 查找策略测试。"""

    def test_injected_path_returned(self) -> None:
        """构造时注入的 ffmpeg_path 被优先返回。"""
        dl = _make_downloader(ffmpeg_path="C:/custom/ffmpeg.exe")
        assert dl._find_ffmpeg() == "C:/custom/ffmpeg.exe"

    def test_none_when_not_found(self) -> None:
        """未注入且 resources 与 PATH 均无 ffmpeg 时返回 None。"""
        dl = _make_downloader(ffmpeg_path=None)
        from downloader.downloader import Path as DPath
        with patch("shutil.which", return_value=None), patch.object(DPath, "exists", return_value=False):
            assert dl._find_ffmpeg() is None

    def test_system_path_fallback(self) -> None:
        """系统 PATH 中存在 ffmpeg 时返回其路径。"""
        dl = _make_downloader(ffmpeg_path=None)
        from downloader.downloader import Path as DPath
        with patch("shutil.which", return_value="C:/bin/ffmpeg.exe"), patch.object(
            DPath, "exists", return_value=False
        ):
            assert dl._find_ffmpeg() == "C:/bin/ffmpeg.exe"


class TestDownloadDash:
    """_download_dash 合并流程测试。"""

    @pytest.mark.asyncio
    async def test_dash_success_merges_and_marks_completed(
        self, tmp_path: Path
    ) -> None:
        """双流下载成功 + ffmpeg 合并成功 → status=completed、返回成功。"""
        dl, item = _make_dash_item(download_dir=str(tmp_path))
        final_path = tmp_path / "测试作者 - 测试视频.mp4"

        # 预创建视频分部并 mock 下载结果为成功（不真实写文件，直接 mock）
        video_result = DownloadResult(success=True, local_path=str(final_path) + ".video")
        audio_result = DownloadResult(success=True, local_path=str(final_path) + ".audio")

        async def fake_download_single_file(task_item, url, final_path, **kwargs):
            # 模拟写一个文件，保证 ffmpeg 合并前文件存在
            Path(str(final_path)).write_bytes(b"stream")
            return video_result if "video" in str(final_path) else audio_result

        with patch.object(dl, "_download_single_file", side_effect=fake_download_single_file), patch.object(
            dl, "_merge_dash_streams", new_callable=AsyncMock
        ) as mock_merge:
            result = await dl._download_dash(item, final_path)

        assert result.success is True
        assert result.local_path is not None
        mock_merge.assert_awaited_once()
        # 状态应为 completed
        status_row = dl._conn.execute(
            "SELECT status, local_path FROM task_items WHERE id=?", (item.id,)
        ).fetchone()
        assert status_row["status"] == "completed"
        assert status_row["local_path"] == result.local_path

    @pytest.mark.asyncio
    async def test_dash_video_failure_marks_failed(self, tmp_path: Path) -> None:
        """视频流下载失败 → status=failed、返回失败。"""
        dl, item = _make_dash_item(download_dir=str(tmp_path))
        final_path = tmp_path / "测试作者 - 测试视频.mp4"

        video_result = DownloadResult(success=False, error="视频流下载失败")

        async def fake_download_single_file(task_item, url, final_path, **kwargs):
            if "video" in str(final_path):
                return video_result
            # 音频流不应被下载（视频先失败时 gather 仍会继续，这里模拟成功）
            Path(str(final_path)).write_bytes(b"audio")
            return DownloadResult(success=True, local_path=str(final_path))

        with patch.object(dl, "_download_single_file", side_effect=fake_download_single_file), patch.object(
            dl, "_merge_dash_streams", new_callable=AsyncMock
        ) as mock_merge:
            result = await dl._download_dash(item, final_path)

        assert result.success is False
        assert result.error == "视频流下载失败"
        mock_merge.assert_not_awaited()
        status_row = dl._conn.execute(
            "SELECT status FROM task_items WHERE id=?", (item.id,)
        ).fetchone()
        assert status_row["status"] == "failed"

    @pytest.mark.asyncio
    async def test_dash_merge_failure_marks_failed(self, tmp_path: Path) -> None:
        """ffmpeg 合并失败 → status=failed、清理临时文件。"""
        dl, item = _make_dash_item(download_dir=str(tmp_path))
        final_path = tmp_path / "测试作者 - 测试视频.mp4"

        async def fake_download_single_file(task_item, url, final_path, **kwargs):
            Path(str(final_path)).write_bytes(b"stream")
            return DownloadResult(success=True, local_path=str(final_path))

        with patch.object(dl, "_download_single_file", side_effect=fake_download_single_file), patch.object(
            dl, "_merge_dash_streams", new_callable=AsyncMock, side_effect=RuntimeError("ffmpeg 未找到")
        ):
            result = await dl._download_dash(item, final_path)

        assert result.success is False
        assert "ffmpeg 未找到" in (result.error or "")
        status_row = dl._conn.execute(
            "SELECT status FROM task_items WHERE id=?", (item.id,)
        ).fetchone()
        assert status_row["status"] == "failed"
        # 临时流文件应被清理
        for ext in (".video", ".audio"):
            assert not Path(str(final_path) + ext).exists()

    @pytest.mark.asyncio
    async def test_download_dispatches_to_dash(self, tmp_path: Path) -> None:
        """download() 对带 audio_url 的任务项走 DASH 流程。"""
        dl, item = _make_dash_item(download_dir=str(tmp_path))
        expected = DownloadResult(success=True, local_path=str(tmp_path / "test.mp4"))
        with patch.object(dl, "_download_dash", new_callable=AsyncMock, return_value=expected) as mock_dash:
            result = await dl.download(item)
            mock_dash.assert_awaited_once()
            assert result is expected
            assert result.success is True
