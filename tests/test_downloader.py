"""Downloader 单元测试。

覆盖正常下载、断点续传、失败重试、暂停/取消、图集下载等场景。
使用 respx mock httpx 响应，不打真实网络请求。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from app.database import get_memory_connection
from app.models import Cookie, Task, TaskItem, VideoType
from app.repositories import CookieRepository, TaskItemRepository, TaskRepository
from crawlers.video_parser import VideoInfo, VideoParser
from downloader.downloader import (
    CHUNK_SIZE,
    LARGE_FILE_THRESHOLD,
    MAX_RETRY_COUNT,
    MAX_SEGMENTS,
    MP4_EXTENSION,
    PERSIST_INTERVAL_BYTES,
    PERSIST_INTERVAL_SECONDS,
    RATE_LIMITED_STATUS_CODES,
    RETRY_BACKOFF_BASE,
    SEGMENT_SIZE,
    WEBP_EXTENSIONS,
    Downloader,
    DownloadResult,
    _select_urls_by_indices,
)
from downloader.progress_reporter import ProgressReporter

# ==================== 常量测试 ====================


class TestConstants:
    """模块级常量契约测试。"""

    def test_chunk_size_64kb(self) -> None:
        assert CHUNK_SIZE == 64 * 1024

    def test_persist_interval_seconds_5(self) -> None:
        assert PERSIST_INTERVAL_SECONDS == 5

    def test_persist_interval_bytes_1mb(self) -> None:
        assert PERSIST_INTERVAL_BYTES == 1024 * 1024

    def test_max_retry_count_3(self) -> None:
        assert MAX_RETRY_COUNT == 3

    def test_retry_backoff_base_2(self) -> None:
        assert RETRY_BACKOFF_BASE == 2

    def test_rate_limited_status_codes(self) -> None:
        assert 461 in RATE_LIMITED_STATUS_CODES
        assert 412 in RATE_LIMITED_STATUS_CODES


# ==================== DownloadResult 测试 ====================


class TestDownloadResult:
    """DownloadResult dataclass 测试。"""

    def test_success_result(self) -> None:
        result = DownloadResult(success=True, local_path="/tmp/video.mp4")
        assert result.success is True
        assert result.local_path == "/tmp/video.mp4"
        assert result.error is None

    def test_failure_result(self) -> None:
        result = DownloadResult(success=False, error="HTTP 404")
        assert result.success is False
        assert result.local_path is None
        assert result.error == "HTTP 404"

    def test_is_frozen(self) -> None:
        result = DownloadResult(success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


# ==================== _should_retry 测试 ====================


class TestShouldRetry:
    """_should_retry 方法测试（设计文档 5.3 节）。"""

    def test_network_error_retry(self) -> None:
        """网络异常触发重试。"""
        dl = _make_downloader()
        assert dl._should_retry(None, httpx.ConnectError("conn")) is True

    def test_read_timeout_retry(self) -> None:
        """ReadTimeout 触发重试。"""
        dl = _make_downloader()
        assert dl._should_retry(None, httpx.ReadTimeout("timeout")) is True

    def test_5xx_retry(self) -> None:
        """HTTP 5xx 触发重试。"""
        dl = _make_downloader()
        assert dl._should_retry(500, None) is True
        assert dl._should_retry(502, None) is True
        assert dl._should_retry(503, None) is True

    def test_461_retry(self) -> None:
        """HTTP 461 风控限流触发重试。"""
        dl = _make_downloader()
        assert dl._should_retry(461, None) is True

    def test_412_retry(self) -> None:
        """HTTP 412 风控限流触发重试。"""
        dl = _make_downloader()
        assert dl._should_retry(412, None) is True

    def test_4xx_no_retry(self) -> None:
        """HTTP 4xx（非 461/412）不重试。"""
        dl = _make_downloader()
        assert dl._should_retry(404, None) is False
        assert dl._should_retry(403, None) is False
        assert dl._should_retry(400, None) is False

    def test_non_http_exception_no_retry(self) -> None:
        """非 httpx.HTTPError 异常不重试。"""
        dl = _make_downloader()
        assert dl._should_retry(None, ValueError("not http")) is False


# ==================== _extract_extension 测试 ====================


class TestExtractExtension:
    """_extract_extension 方法测试。"""

    def test_mp4_extension(self) -> None:
        url = "https://example.com/video.mp4?token=x"
        assert Downloader._extract_extension(url, "video") == ".mp4"

    def test_jpg_extension(self) -> None:
        assert Downloader._extract_extension("https://example.com/image.jpg", "image_set") == ".jpg"

    def test_no_extension_video_defaults_mp4(self) -> None:
        assert Downloader._extract_extension("https://example.com/noext", "video") == ".mp4"

    def test_no_extension_image_defaults_jpg(self) -> None:
        assert Downloader._extract_extension("https://example.com/noext", "image_set") == ".jpg"


# ==================== 路径推导测试 ====================


class TestPathDerivation:
    """_get_final_path / _get_part_path / _get_download_dir 测试。"""

    def test_get_download_dir(self, tmp_path: Path) -> None:
        """_get_download_dir 返回 task 的 download_dir。"""
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        assert dl._get_download_dir(item) == tmp_path

    def test_get_download_dir_raises_if_task_missing(self) -> None:
        """task 不存在时抛 ValueError。"""
        dl = _make_downloader()
        item = TaskItem(id=999, task_id=999, aweme_id="x", url="https://x.com/v", type="video")
        with pytest.raises(ValueError, match="download_dir"):
            dl._get_download_dir(item)

    def test_get_final_path_video(self, tmp_path: Path) -> None:
        """video 类型路径：{download_dir}/{aweme_id}.mp4"""
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme123")
        path = dl._get_final_path(item, "https://example.com/video.mp4")
        assert path == tmp_path / "aweme123.mp4"

    def test_get_final_path_image_set(self, tmp_path: Path) -> None:
        """image_set 类型路径：{download_dir}/{基础名}/{基础名}-{index}.jpg"""
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path), aweme_id="aweme456", item_type="image_set"
        )
        path = dl._get_final_path(item, "https://example.com/img.jpg", index=2)
        assert path == tmp_path / "aweme456" / "aweme456-2.jpg"

    def test_get_final_path_video_uses_author_and_title(self, tmp_path: Path) -> None:
        """video 命名（问题归档 #4）：作者名 + 源媒体标题。"""
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="aweme123",
            title="一条测试视频",
            author="@张三",
        )
        path = dl._get_final_path(item, "https://example.com/video.mp4")
        assert path == tmp_path / "@张三一条测试视频.mp4"

    def test_get_final_path_sanitizes_illegal_chars(self, tmp_path: Path) -> None:
        """Windows 非法字符替换为下划线。"""
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="aweme123",
            title='标题:含"非法/符\\号?*字符',
            author="作者",
        )
        path = dl._get_final_path(item, "https://example.com/video.mp4")
        assert path.name == "作者标题_含_非法_符_号__字符.mp4"

    def test_get_final_path_truncates_long_title(self, tmp_path: Path) -> None:
        """超长标题截取前 MAX_FILENAME_BASE_LENGTH 字。"""
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="aweme123",
            title="超长标题" * 30,
            author="作者",
        )
        path = dl._get_final_path(item, "https://example.com/video.mp4")
        assert path.stem == ("作者" + "超长标题" * 30)[:50]
        assert len(path.stem) == 50

    def test_get_final_path_image_set_uses_author_and_title(self, tmp_path: Path) -> None:
        """image_set 命名（问题归档 #4）：同名文件夹 + -{index} 后缀。"""
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="aweme456",
            item_type="image_set",
            title="旅游图集",
            author="@李四",
        )
        path = dl._get_final_path(item, "https://example.com/img.jpg", index=1)
        assert path == tmp_path / "@李四旅游图集" / "@李四旅游图集-1.jpg"

    def test_get_final_path_no_aweme_id(self, tmp_path: Path) -> None:
        """aweme_id 为 None 时用 item_{id} 替代。"""
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id=None, item_id=42)
        path = dl._get_final_path(item, "https://example.com/v.mp4")
        assert "item_42" in path.name

    def test_get_part_path(self, tmp_path: Path) -> None:
        """_get_part_path 在最终路径后追加 .part。"""
        final = tmp_path / "video.mp4"
        dl = _make_downloader()
        part = dl._get_part_path(final)
        assert str(part) == str(final) + ".part"


# ==================== _finalize_file 测试 ====================


class TestFinalizeFile:
    """_finalize_file 方法测试。"""

    def test_rename_part_to_final(self, tmp_path: Path) -> None:
        """_finalize_file 将 .part 重命名为最终文件。"""
        part = tmp_path / "video.mp4.part"
        final = tmp_path / "video.mp4"
        part.write_bytes(b"data")
        dl = _make_downloader()
        result = dl._finalize_file(part, final)
        assert final.exists()
        assert not part.exists()
        assert result == str(final)

    def test_overwrite_existing_final(self, tmp_path: Path) -> None:
        """最终文件已存在时先删除再重命名。"""
        part = tmp_path / "video.mp4.part"
        final = tmp_path / "video.mp4"
        part.write_bytes(b"new")
        final.write_bytes(b"old")
        dl = _make_downloader()
        dl._finalize_file(part, final)
        assert final.read_bytes() == b"new"


# ==================== _mark_status / _persist_progress 测试 ====================


class TestStatusPersistence:
    """_mark_status 与 _persist_progress 测试。"""

    def test_mark_status_downloading(self) -> None:
        """_mark_status 更新状态为 downloading。"""
        dl, item = _make_downloader_with_item()
        _insert_item(dl._conn, item)
        dl._mark_status(item.id, "downloading")
        assert _get_item_status(dl._conn, item.id) == "downloading"

    def test_mark_status_failed_with_reason(self) -> None:
        """_mark_status 更新状态为 failed 并记录 fail_reason。"""
        dl, item = _make_downloader_with_item()
        _insert_item(dl._conn, item)
        dl._mark_status(item.id, "failed", fail_reason="HTTP 500")
        assert _get_item_status(dl._conn, item.id) == "failed"
        assert _get_item_fail_reason(dl._conn, item.id) == "HTTP 500"

    def test_mark_status_completed_with_path(self) -> None:
        """_mark_status 更新状态为 completed 并记录 local_path。"""
        dl, item = _make_downloader_with_item()
        _insert_item(dl._conn, item)
        dl._mark_status(item.id, "completed", local_path="/tmp/video.mp4")
        assert _get_item_status(dl._conn, item.id) == "completed"
        assert _get_item_local_path(dl._conn, item.id) == "/tmp/video.mp4"

    def test_persist_progress(self) -> None:
        """_persist_progress 更新 downloaded_bytes 和 total_bytes。"""
        dl, item = _make_downloader_with_item()
        _insert_item(dl._conn, item)
        dl._persist_progress(item.id, 512, 1024)
        row = dl._conn.execute(
            "SELECT downloaded_bytes, total_bytes FROM task_items WHERE id=?", (item.id,)
        ).fetchone()
        assert row["downloaded_bytes"] == 512
        assert row["total_bytes"] == 1024


# ==================== 正常下载测试 ====================


class TestDownloadSingleFile:
    """_download_single_file 正常下载流程测试。"""

    @respx.mock
    async def test_download_video_streaming(self, tmp_path: Path) -> None:
        """视频文件流式接收、写入 .part、完成后重命名。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        data = b"video_content_12345"
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(
                200, content=data, headers={"Content-Length": str(len(data))}
            )
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True
        assert final_path.exists()
        assert final_path.read_bytes() == data

    @respx.mock
    async def test_download_writes_part_file(self, tmp_path: Path) -> None:
        """下载过程中文件以 .part 后缀保存。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        data = b"abc" * 100
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=data)
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        await dl._download_single_file(item, item.url, final_path)
        # 完成后 .part 已重命名，不应存在
        part_path = Path(str(final_path) + ".part")
        assert not part_path.exists()

    @respx.mock
    async def test_download_rename_part_to_final(self, tmp_path: Path) -> None:
        """完成后 .part 重命名为最终文件名，local_path 正确。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        data = b"final_content"
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=data)
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.local_path == str(final_path)
        assert final_path.exists()

    @respx.mock
    async def test_download_status_completed(self, tmp_path: Path) -> None:
        """下载完成后 status=completed。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=b"data")
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        await dl._download_single_file(item, item.url, final_path)
        assert _get_item_status(dl._conn, item.id) == "completed"

    @respx.mock
    async def test_download_updates_progress_reporter(self, tmp_path: Path) -> None:
        """下载过程中调用 progress_reporter.update()。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        data = b"x" * (CHUNK_SIZE + 100)  # 超过一个 chunk
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=data)
        )
        reporter = MagicMock(spec=ProgressReporter)
        reporter.update = MagicMock()
        conn = get_memory_connection()
        dl = _make_downloader(conn=conn, reporter=reporter)
        _, item = _make_downloader_with_item(download_dir=str(tmp_path), conn=conn)
        _insert_item(conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        await dl._download_single_file(item, item.url, final_path)
        assert reporter.update.called

    @respx.mock
    async def test_download_persists_progress(self, tmp_path: Path) -> None:
        """下载完成后持久化 downloaded_bytes 到 SQLite。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        data = b"persist_data_12345"
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=data)
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        await dl._download_single_file(item, item.url, final_path)
        row = dl._conn.execute(
            "SELECT downloaded_bytes FROM task_items WHERE id=?", (item.id,)
        ).fetchone()
        assert row["downloaded_bytes"] == len(data)


# ==================== 断点续传测试 ====================


class TestResumeDownload:
    """断点续传测试。"""

    @respx.mock
    async def test_resume_from_part_file(self, tmp_path: Path) -> None:
        """.part 文件存在时从断点继续。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        existing_data = b"already_downloaded"
        remaining_data = b"_rest_of_file"
        full_data = existing_data + remaining_data
        final_path = tmp_path / "aweme001.mp4"
        part_path = Path(str(final_path) + ".part")
        part_path.write_bytes(existing_data)

        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(
                206,
                content=remaining_data,
                headers={"Content-Length": str(len(remaining_data))},
            )
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme001")
        _insert_item(dl._conn, item)
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True
        assert final_path.read_bytes() == full_data

    @respx.mock
    async def test_range_request_correct(self, tmp_path: Path) -> None:
        """续传时发送正确的 Range 请求头。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        existing_data = b"1234567890"
        part_path = tmp_path / "aweme001.mp4.part"
        part_path.write_bytes(existing_data)

        route = respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(206, content=b"rest", headers={"Content-Length": "4"})
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme001")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme001.mp4"
        await dl._download_single_file(item, item.url, final_path)
        request = route.calls[0].request
        assert request.headers.get("Range") == f"bytes={len(existing_data)}-"

    @respx.mock
    async def test_server_returns_200_no_range_support(self, tmp_path: Path) -> None:
        """服务端不支持 Range（返回 200）时从头下载。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        part_path = tmp_path / "aweme001.mp4.part"
        part_path.write_bytes(b"old_partial_data")
        full_data = b"completely_new_file_content"
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=full_data)
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme001")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme001.mp4"
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True
        assert final_path.read_bytes() == full_data


# ==================== 失败重试测试 ====================


class TestRetry:
    """失败重试测试（设计文档 5.3 节）。"""

    @respx.mock
    async def test_retry_on_5xx(self, tmp_path: Path) -> None:
        """HTTP 5xx 触发重试，最终成功。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        data = b"success_after_retry"
        route = respx.get("https://cdn.example.com/v.mp4").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(200, content=data),
            ]
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        with patch("downloader.downloader.asyncio.sleep", new=AsyncMock()):
            result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True
        assert route.call_count == 2

    @respx.mock
    async def test_retry_on_461(self, tmp_path: Path) -> None:
        """HTTP 461 风控限流触发重试。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(
            side_effect=[
                httpx.Response(461),
                httpx.Response(200, content=b"ok"),
            ]
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        with patch("downloader.downloader.asyncio.sleep", new=AsyncMock()):
            result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True

    @respx.mock
    async def test_retry_on_412(self, tmp_path: Path) -> None:
        """HTTP 412 风控限流触发重试。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(
            side_effect=[
                httpx.Response(412),
                httpx.Response(200, content=b"ok"),
            ]
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        with patch("downloader.downloader.asyncio.sleep", new=AsyncMock()):
            result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True

    @respx.mock
    async def test_retry_on_network_error(self, tmp_path: Path) -> None:
        """网络异常触发重试，最终成功。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(
            side_effect=[
                httpx.ConnectError("conn refused"),
                httpx.Response(200, content=b"ok"),
            ]
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        with patch("downloader.downloader.asyncio.sleep", new=AsyncMock()):
            result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True

    @respx.mock
    async def test_max_retry_3_then_failed(self, tmp_path: Path) -> None:
        """重试 3 次仍失败 → status=failed。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(500))
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        with patch("downloader.downloader.asyncio.sleep", new=AsyncMock()):
            result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is False
        assert "重试耗尽" in result.error
        assert _get_item_status(dl._conn, item.id) == "failed"

    @respx.mock
    async def test_4xx_no_retry(self, tmp_path: Path) -> None:
        """HTTP 4xx（非 461/412）直接失败不重试。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        route = respx.get("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is False
        assert "404" in result.error
        assert route.call_count == 1  # 未重试
        assert _get_item_status(dl._conn, item.id) == "failed"

    @respx.mock
    async def test_exponential_backoff_2_4_8(self, tmp_path: Path) -> None:
        """指数退避等待 2s/4s/8s。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(500))
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        mock_sleep = AsyncMock()
        with patch("downloader.downloader.asyncio.sleep", new=mock_sleep):
            await dl._download_single_file(item, item.url, final_path)
        # 验证等待时间：2^1=2, 2^2=4, 2^3=8
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [2, 4, 8]

    @respx.mock
    async def test_retry_count_persisted(self, tmp_path: Path) -> None:
        """retry_count 持久化到 SQLite。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(500))
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        with patch("downloader.downloader.asyncio.sleep", new=AsyncMock()):
            await dl._download_single_file(item, item.url, final_path)
        row = dl._conn.execute(
            "SELECT retry_count FROM task_items WHERE id=?", (item.id,)
        ).fetchone()
        assert row["retry_count"] == MAX_RETRY_COUNT + 1  # 重试 3 次后 +1 = 4


# ==================== 暂停/取消测试 ====================


class TestCancelDownload:
    """CancelledError 处理测试。"""

    @staticmethod
    def _slow_streamer() -> httpx.Response:
        """构造慢速流式响应：每块 64KB 后暂停 1 秒，共 5 块。"""

        async def generate():
            for _ in range(5):
                yield b"x" * CHUNK_SIZE
                await asyncio.sleep(1)

        return httpx.Response(
            200,
            content=generate(),
            headers={"Content-Length": str(CHUNK_SIZE * 5)},
        )

    @respx.mock
    async def test_cancel_persists_progress(self, tmp_path: Path) -> None:
        """CancelledError 时持久化当前 downloaded_bytes。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(return_value=self._slow_streamer())

        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"

        task = asyncio.create_task(dl._download_single_file(item, item.url, final_path))
        await asyncio.sleep(0.5)  # 等待第一块下载完成
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # 验证进度已持久化
        row = dl._conn.execute(
            "SELECT downloaded_bytes FROM task_items WHERE id=?", (item.id,)
        ).fetchone()
        assert row["downloaded_bytes"] > 0

    @respx.mock
    async def test_cancel_keeps_part_file(self, tmp_path: Path) -> None:
        """取消后保留 .part 文件。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(return_value=self._slow_streamer())
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        part_path = Path(str(final_path) + ".part")

        task = asyncio.create_task(dl._download_single_file(item, item.url, final_path))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert part_path.exists()

    @respx.mock
    async def test_cancel_does_not_mark_completed(self, tmp_path: Path) -> None:
        """Downloader 内部不修改 status 为 paused（由调度器负责）。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(return_value=self._slow_streamer())
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        final_path = tmp_path / f"{item.aweme_id}.mp4"
        # 模拟 download() 入口的置 downloading（_download_single_file 不负责设置）
        dl._mark_status(item.id, "downloading")

        task = asyncio.create_task(dl._download_single_file(item, item.url, final_path))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # status 应保持 downloading（未被改为 paused 或 completed）
        assert _get_item_status(dl._conn, item.id) == "downloading"


# ==================== 图集下载测试 ====================


class TestDownloadImageSet:
    """图集并发下载测试。"""

    @respx.mock
    async def test_image_set_concurrent_download(self, tmp_path: Path) -> None:
        """多图片 URL 并发下载全部成功。"""
        urls = [
            "https://cdn.example.com/img1.jpg",
            "https://cdn.example.com/img2.jpg",
            "https://cdn.example.com/img3.jpg",
        ]
        for url in urls:
            respx.head(url).mock(return_value=httpx.Response(404))
            respx.get(url).mock(
                return_value=httpx.Response(200, content=b"img_data_" + url[-9:-4].encode())
            )
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="img_set_001",
            item_type="image_set",
            url="\n".join(urls),
        )
        _insert_item(dl._conn, item)
        result = await dl.download(item)
        assert result.success is True
        assert _get_item_status(dl._conn, item.id) == "completed"

    @respx.mock
    async def test_image_set_partial_failure(self, tmp_path: Path) -> None:
        """任一图片失败 → 整个图集标记失败。"""
        urls = [
            "https://cdn.example.com/img1.jpg",
            "https://cdn.example.com/img2.jpg",
        ]
        respx.head(urls[0]).mock(return_value=httpx.Response(404))
        respx.head(urls[1]).mock(return_value=httpx.Response(404))
        respx.get(urls[0]).mock(return_value=httpx.Response(200, content=b"ok"))
        respx.get(urls[1]).mock(return_value=httpx.Response(404))
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="img_set_002",
            item_type="image_set",
            url="\n".join(urls),
        )
        _insert_item(dl._conn, item)
        result = await dl.download(item)
        assert result.success is False
        assert _get_item_status(dl._conn, item.id) == "failed"

    @respx.mock
    async def test_image_set_empty_urls(self, tmp_path: Path) -> None:
        """图集 URL 为空时直接失败。"""
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            item_type="image_set",
            url="\n\n  \n",  # 只有空白行
        )
        _insert_item(dl._conn, item)
        result = await dl.download(item)
        assert result.success is False
        assert _get_item_status(dl._conn, item.id) == "failed"


# ==================== 图集直链失效重新解析测试（v0.1.7 plan 6.6）====================


def _make_video_info(image_urls: list[str], aweme_id: str = "aweme001") -> VideoInfo:
    """构造测试用 VideoInfo。"""
    return VideoInfo(
        aweme_id=aweme_id,
        type=VideoType.IMAGE_SET,
        title="测试图集",
        author="作者",
        author_sec_id="sec_id",
        duration=None,
        cover_url="https://example.com/cover.jpg",
        no_watermark_url=None,
        image_urls=image_urls,
        publish_time=None,
        like_count=0,
        comment_count=0,
        share_count=0,
        collect_count=0,
        tags=[],
        raw_json={},
    )


def _make_reparse_deps(
    image_urls: list[str] | None = None,
    parse_side_effect: Exception | None = None,
) -> tuple[MagicMock, MagicMock]:
    """构造 video_parser + cookie_repository mock 依赖。

    Args:
        image_urls: parse_video 成功时返回的 image_urls；
            为 None 且 parse_side_effect 为 None 时默认 ["new1", "new2"]
        parse_side_effect: parse_video 抛出的异常；非 None 时优先使用
    """
    video_parser = MagicMock(spec=VideoParser)
    if parse_side_effect is not None:
        video_parser.parse_video = AsyncMock(side_effect=parse_side_effect)
    else:
        urls = image_urls if image_urls is not None else ["new1", "new2"]
        video_parser.parse_video = AsyncMock(return_value=_make_video_info(urls))
    cookie_repo = MagicMock(spec=CookieRepository)
    cookie_repo.get_valid.return_value = Cookie(id=1, content="ck=test")
    return video_parser, cookie_repo


class TestSelectUrlsByIndices:
    """_select_urls_by_indices 模块级函数测试。"""

    def test_empty_string_selects_all(self) -> None:
        """空 selected_indices_str 表示全选。"""
        assert _select_urls_by_indices(["a", "b", "c"], "") == ["a", "b", "c"]

    def test_partial_selection(self) -> None:
        """部分选择。"""
        assert _select_urls_by_indices(["a", "b", "c"], "[0, 2]") == ["a", "c"]

    def test_invalid_json_selects_all(self) -> None:
        """非法 JSON 按全选处理。"""
        assert _select_urls_by_indices(["a", "b"], "invalid") == ["a", "b"]

    def test_non_list_json_selects_all(self) -> None:
        """非数组 JSON 按全选处理。"""
        assert _select_urls_by_indices(["a", "b"], "0") == ["a", "b"]

    def test_out_of_range_index_skipped(self) -> None:
        """越界索引被跳过。"""
        assert _select_urls_by_indices(["a", "b"], "[0, 5]") == ["a"]


class TestIsLinkExpired:
    """_is_link_expired 判定测试。"""

    def test_403_is_expired(self) -> None:
        """HTTP 403 判定为直链失效。"""
        dl = _make_downloader()
        assert dl._is_link_expired("HTTP 403") is True

    def test_404_is_expired(self) -> None:
        """HTTP 404 判定为直链失效。"""
        dl = _make_downloader()
        assert dl._is_link_expired("HTTP 404") is True

    def test_500_not_expired(self) -> None:
        """HTTP 500 不判定为直链失效。"""
        dl = _make_downloader()
        assert dl._is_link_expired("HTTP 500") is False

    def test_none_not_expired(self) -> None:
        """None 不判定为直链失效。"""
        dl = _make_downloader()
        assert dl._is_link_expired(None) is False


class TestCanReparse:
    """_can_reparse 能力判定测试。"""

    def test_both_injected_can_reparse(self) -> None:
        """两个依赖都注入时返回 True。"""
        video_parser, cookie_repo = _make_reparse_deps()
        dl = _make_downloader(video_parser=video_parser, cookie_repository=cookie_repo)
        assert dl._can_reparse() is True

    def test_none_injected_cannot_reparse(self) -> None:
        """无依赖注入时返回 False。"""
        dl = _make_downloader()
        assert dl._can_reparse() is False

    def test_only_parser_cannot_reparse(self) -> None:
        """仅注入 video_parser 返回 False。"""
        video_parser, _ = _make_reparse_deps()
        dl = _make_downloader(video_parser=video_parser)
        assert dl._can_reparse() is False


class TestGetCookieString:
    """_get_cookie_string 测试。"""

    def test_returns_content_when_valid(self) -> None:
        """有 valid cookie 返回 content。"""
        video_parser, cookie_repo = _make_reparse_deps()
        dl = _make_downloader(video_parser=video_parser, cookie_repository=cookie_repo)
        assert dl._get_cookie_string() == "ck=test"

    def test_returns_none_when_no_valid(self) -> None:
        """无 valid cookie 返回 None。"""
        video_parser = MagicMock(spec=VideoParser)
        cookie_repo = MagicMock(spec=CookieRepository)
        cookie_repo.get_valid.return_value = None
        dl = _make_downloader(video_parser=video_parser, cookie_repository=cookie_repo)
        assert dl._get_cookie_string() is None


class TestReparseSingleImageUrl:
    """_reparse_single_image_url 测试。"""

    async def test_reparse_success_returns_url(self) -> None:
        """重新解析成功返回对应索引的 url。"""
        video_parser, cookie_repo = _make_reparse_deps(image_urls=["new0", "new1", "new2"])
        dl, item = _make_downloader_with_item(
            aweme_id="aweme001",
            video_parser=video_parser,
            cookie_repository=cookie_repo,
        )
        new_url = await dl._reparse_single_image_url(item, 1)
        assert new_url == "new1"

    async def test_reparse_with_selected_indices(self) -> None:
        """带 selected_image_indices 时按索引筛选。"""
        video_parser, cookie_repo = _make_reparse_deps(image_urls=["new0", "new1", "new2", "new3"])
        dl, item = _make_downloader_with_item(
            aweme_id="aweme001",
            video_parser=video_parser,
            cookie_repository=cookie_repo,
        )
        item.selected_image_indices = "[0, 2]"  # 筛选后 = [new0, new2]
        new_url = await dl._reparse_single_image_url(item, 1)  # 子集 idx=1 → new2
        assert new_url == "new2"

    async def test_reparse_no_parser_returns_none(self) -> None:
        """无 video_parser 返回 None。"""
        dl, item = _make_downloader_with_item()
        assert await dl._reparse_single_image_url(item, 0) is None

    async def test_reparse_parse_fails_returns_none(self) -> None:
        """parse_video 抛异常时返回 None。"""
        video_parser, cookie_repo = _make_reparse_deps(parse_side_effect=RuntimeError("network"))
        dl, item = _make_downloader_with_item(
            aweme_id="aweme001",
            video_parser=video_parser,
            cookie_repository=cookie_repo,
        )
        assert await dl._reparse_single_image_url(item, 0) is None

    async def test_reparse_no_cookie_returns_none(self) -> None:
        """无可用 cookie 返回 None。"""
        video_parser = MagicMock(spec=VideoParser)
        cookie_repo = MagicMock(spec=CookieRepository)
        cookie_repo.get_valid.return_value = None
        dl, item = _make_downloader_with_item(
            aweme_id="aweme001",
            video_parser=video_parser,
            cookie_repository=cookie_repo,
        )
        assert await dl._reparse_single_image_url(item, 0) is None

    async def test_reparse_no_aweme_id_returns_none(self) -> None:
        """aweme_id 为 None 返回 None。"""
        video_parser, cookie_repo = _make_reparse_deps()
        dl, item = _make_downloader_with_item(
            video_parser=video_parser,
            cookie_repository=cookie_repo,
        )
        item.aweme_id = None
        assert await dl._reparse_single_image_url(item, 0) is None

    async def test_reparse_index_out_of_range_returns_none(self) -> None:
        """重新解析后索引越界返回 None。"""
        video_parser, cookie_repo = _make_reparse_deps(image_urls=["only_one"])
        dl, item = _make_downloader_with_item(
            aweme_id="aweme001",
            video_parser=video_parser,
            cookie_repository=cookie_repo,
        )
        assert await dl._reparse_single_image_url(item, 5) is None


class TestImageSetReparseIntegration:
    """图集下载集成：4xx 失效触发重新解析。"""

    @respx.mock
    async def test_image_set_reparse_on_403_then_success(self, tmp_path: Path) -> None:
        """图集 403 失效触发重新解析，重试成功。"""
        old_urls = [
            "https://cdn.example.com/old1.jpg",
            "https://cdn.example.com/old2.jpg",
        ]
        new_urls = [
            "https://cdn.example.com/new1.jpg",
            "https://cdn.example.com/new2.jpg",
        ]
        # 旧 url 返回 403
        for u in old_urls:
            respx.head(u).mock(return_value=httpx.Response(403))
            respx.get(u).mock(return_value=httpx.Response(403))
        # 新 url 返回 200
        for u in new_urls:
            respx.head(u).mock(return_value=httpx.Response(404))
            respx.get(u).mock(return_value=httpx.Response(200, content=b"img"))
        video_parser, cookie_repo = _make_reparse_deps(image_urls=new_urls)
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="aweme001",
            item_type="image_set",
            url="\n".join(old_urls),
            video_parser=video_parser,
            cookie_repository=cookie_repo,
        )
        _insert_item(dl._conn, item)
        result = await dl.download(item)
        assert result.success is True
        assert _get_item_status(dl._conn, item.id) == "completed"
        # parse_video 被调用（每张失败图片触发一次）
        assert video_parser.parse_video.await_count >= 1

    @respx.mock
    async def test_image_set_reparse_failure_marks_failed(self, tmp_path: Path) -> None:
        """重新解析失败则按原失败标记 failed。"""
        old_urls = ["https://cdn.example.com/old1.jpg"]
        respx.head(old_urls[0]).mock(return_value=httpx.Response(404))
        respx.get(old_urls[0]).mock(return_value=httpx.Response(404))
        video_parser, cookie_repo = _make_reparse_deps(parse_side_effect=RuntimeError("network"))
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="aweme001",
            item_type="image_set",
            url="\n".join(old_urls),
            video_parser=video_parser,
            cookie_repository=cookie_repo,
        )
        _insert_item(dl._conn, item)
        result = await dl.download(item)
        assert result.success is False
        assert _get_item_status(dl._conn, item.id) == "failed"

    @respx.mock
    async def test_image_set_no_reparse_when_no_parser(self, tmp_path: Path) -> None:
        """无 video_parser 注入时 4xx 直接失败不重新解析。"""
        urls = ["https://cdn.example.com/old1.jpg"]
        respx.head(urls[0]).mock(return_value=httpx.Response(403))
        respx.get(urls[0]).mock(return_value=httpx.Response(403))
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="aweme001",
            item_type="image_set",
            url="\n".join(urls),
        )
        _insert_item(dl._conn, item)
        result = await dl.download(item)
        assert result.success is False
        assert _get_item_status(dl._conn, item.id) == "failed"


# ==================== download 主入口测试 ====================


class TestDownloadEntry:
    """download() 主入口分发测试。"""

    @respx.mock
    async def test_download_video_dispatches_single_file(self, tmp_path: Path) -> None:
        """video 类型走 _download_single_file 分支。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=b"video")
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        result = await dl.download(item)
        assert result.success is True
        assert _get_item_status(dl._conn, item.id) == "completed"

    @respx.mock
    async def test_download_marks_downloading_first(self, tmp_path: Path) -> None:
        """download() 首先将 status 置为 downloading。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=b"data")
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path))
        _insert_item(dl._conn, item)
        await dl.download(item)
        # 最终是 completed，但过程中先变 downloading
        assert _get_item_status(dl._conn, item.id) == "completed"


# ==================== 辅助函数 ====================


def _make_downloader(
    conn: sqlite3.Connection | None = None,
    reporter: ProgressReporter | None = None,
    video_parser: VideoParser | None = None,
    cookie_repository: CookieRepository | None = None,
    webp_auto_convert: bool = False,
) -> Downloader:
    """创建测试用 Downloader（不依赖真实 DB 数据）。"""
    if conn is None:
        conn = get_memory_connection()
    if reporter is None:
        reporter = MagicMock(spec=ProgressReporter)
    http_client = httpx.AsyncClient()
    semaphore = asyncio.Semaphore(10)
    return Downloader(
        reporter,
        http_client,
        semaphore,
        conn,
        video_parser=video_parser,
        cookie_repository=cookie_repository,
        webp_auto_convert=webp_auto_convert,
    )


def _make_downloader_with_reporter(reporter: ProgressReporter) -> Downloader:
    """用指定 reporter 创建 Downloader。"""
    return _make_downloader(reporter=reporter)


def _make_downloader_with_item(
    download_dir: str = "/tmp/test_downloads",
    aweme_id: str = "aweme001",
    item_type: str = "video",
    url: str = "https://cdn.example.com/v.mp4",
    item_id: int = 1,
    task_id: int = 1,
    title: str | None = None,
    author: str | None = None,
    conn: sqlite3.Connection | None = None,
    video_parser: VideoParser | None = None,
    cookie_repository: CookieRepository | None = None,
    webp_auto_convert: bool = False,
) -> tuple[Downloader, TaskItem]:
    """创建 Downloader 并关联一个已插入 task 的 TaskItem（未插入 task_items 表）。"""
    if conn is None:
        conn = get_memory_connection()
    task_repo = TaskRepository(conn)
    task_repo.create(
        Task(
            id=None,
            source_type="single",
            source_url="https://douyin.com/video/123",
            status="pending",
            total_items=1,
            download_dir=download_dir,
        )
    )
    reporter = MagicMock(spec=ProgressReporter)
    http_client = httpx.AsyncClient()
    semaphore = asyncio.Semaphore(10)
    dl = Downloader(
        reporter,
        http_client,
        semaphore,
        conn,
        video_parser=video_parser,
        cookie_repository=cookie_repository,
        webp_auto_convert=webp_auto_convert,
    )
    item = TaskItem(
        id=item_id,
        task_id=task_id,
        aweme_id=aweme_id,
        url=url,
        type=item_type,
        status="pending",
        title=title,
        author=author,
    )
    return dl, item


def _insert_item(conn: sqlite3.Connection, item: TaskItem) -> None:
    """将 TaskItem 插入数据库（如果尚未插入）。"""
    existing = conn.execute("SELECT id FROM task_items WHERE id=?", (item.id,)).fetchone()
    if existing is None:
        TaskItemRepository(conn).create(item)


def _get_item_status(conn: sqlite3.Connection, item_id: int) -> str:
    row = conn.execute("SELECT status FROM task_items WHERE id=?", (item_id,)).fetchone()
    return row["status"] if row else ""


def _get_item_fail_reason(conn: sqlite3.Connection, item_id: int) -> str | None:
    row = conn.execute("SELECT fail_reason FROM task_items WHERE id=?", (item_id,)).fetchone()
    return row["fail_reason"] if row else None


def _get_item_local_path(conn: sqlite3.Connection, item_id: int) -> str | None:
    row = conn.execute("SELECT local_path FROM task_items WHERE id=?", (item_id,)).fetchone()
    return row["local_path"] if row else None


# ==================== 分片下载：_get_file_size 测试 ====================


class TestGetFileSize:
    """_get_file_size 方法测试（HEAD 请求获取文件大小）。"""

    @respx.mock
    async def test_head_success_returns_content_length(self) -> None:
        """HEAD 200 且带 Content-Length → 返回字节数。"""
        respx.head("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, headers={"Content-Length": "12345"})
        )
        dl = _make_downloader()
        result = await dl._get_file_size("https://cdn.example.com/v.mp4")
        assert result == 12345

    @respx.mock
    async def test_head_404_returns_none(self) -> None:
        """HEAD 404 → 返回 None。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(404))
        dl = _make_downloader()
        result = await dl._get_file_size("https://cdn.example.com/v.mp4")
        assert result is None

    @respx.mock
    async def test_head_no_content_length_returns_none(self) -> None:
        """HEAD 200 但无 Content-Length → 返回 None。"""
        respx.head("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(200))
        dl = _make_downloader()
        result = await dl._get_file_size("https://cdn.example.com/v.mp4")
        assert result is None

    @respx.mock
    async def test_head_network_error_returns_none(self) -> None:
        """HEAD 网络异常 → 返回 None，不抛异常。"""
        respx.head("https://cdn.example.com/v.mp4").mock(
            side_effect=httpx.ConnectError("conn refused")
        )
        dl = _make_downloader()
        result = await dl._get_file_size("https://cdn.example.com/v.mp4")
        assert result is None


# ==================== 分片下载：_calculate_segments 测试 ====================


class TestCalculateSegments:
    """_calculate_segments 静态方法测试。"""

    def test_12mb_creates_6_segments(self) -> None:
        """12MB → 6 个分片，每片 2MB。"""
        total = 12 * 1024 * 1024
        segments = Downloader._calculate_segments(total)
        assert len(segments) == 6
        for start, end in segments:
            assert end - start + 1 == SEGMENT_SIZE

    def test_50mb_creates_8_segments_capped(self) -> None:
        """50MB → 8 个分片（受 MAX_SEGMENTS 限制）。"""
        total = 50 * 1024 * 1024
        segments = Downloader._calculate_segments(total)
        assert len(segments) == MAX_SEGMENTS

    def test_5mb_creates_3_segments(self) -> None:
        """5MB → 3 个分片。"""
        total = 5 * 1024 * 1024
        segments = Downloader._calculate_segments(total)
        assert len(segments) == 3

    def test_segments_cover_full_range(self) -> None:
        """首片 start=0，末片 end=total-1。"""
        total = 12 * 1024 * 1024
        segments = Downloader._calculate_segments(total)
        assert segments[0][0] == 0
        assert segments[-1][1] == total - 1

    def test_exact_multiple_of_segment_size(self) -> None:
        """4MB（SEGMENT_SIZE 的 2 倍）→ 2 个分片，无间隙。"""
        total = 4 * 1024 * 1024
        segments = Downloader._calculate_segments(total)
        assert len(segments) == 2
        for i in range(len(segments) - 1):
            assert segments[i][1] + 1 == segments[i + 1][0]

    def test_just_above_threshold(self) -> None:
        """LARGE_FILE_THRESHOLD + 1 → 正确分片数。"""
        total = LARGE_FILE_THRESHOLD + 1
        segments = Downloader._calculate_segments(total)
        # ceil((10*1024*1024 + 1) / (2*1024*1024)) = 6
        assert len(segments) == 6


# ==================== 分片下载：_download_segment 测试 ====================


class TestDownloadSegment:
    """_download_segment 方法测试（单分片下载）。"""

    @respx.mock
    async def test_normal_download(self, tmp_path: Path) -> None:
        """正常分片下载：206 响应写入 .part 文件，返回字节数，on_chunk 被调用。"""
        data = b"segment_data_12345"
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(
                206, content=data, headers={"Content-Length": str(len(data))}
            )
        )
        dl = _make_downloader()
        part_path = tmp_path / "video.part.0"
        on_chunk = MagicMock()
        result = await dl._download_segment(
            "https://cdn.example.com/v.mp4", part_path, 0, len(data) - 1, on_chunk
        )
        assert result == len(data)
        assert part_path.read_bytes() == data
        on_chunk.assert_called()
        total_reported = sum(call.args[0] for call in on_chunk.call_args_list)
        assert total_reported == len(data)

    @respx.mock
    async def test_resume_from_partial(self, tmp_path: Path) -> None:
        """断点续传：.part 文件已存在时追加下载剩余部分。"""
        existing = b"already_downloaded"
        remaining = b"_rest"
        full = existing + remaining
        part_path = tmp_path / "video.part.0"
        part_path.write_bytes(existing)
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(
                206,
                content=remaining,
                headers={"Content-Length": str(len(remaining))},
            )
        )
        dl = _make_downloader()
        result = await dl._download_segment(
            "https://cdn.example.com/v.mp4",
            part_path,
            0,
            len(full) - 1,
            MagicMock(),
        )
        assert result == len(full)
        assert part_path.read_bytes() == full

    @respx.mock
    async def test_retry_on_500_then_success(self, tmp_path: Path) -> None:
        """HTTP 500 后重试成功。"""
        data = b"success_after_retry"
        respx.get("https://cdn.example.com/v.mp4").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(206, content=data, headers={"Content-Length": str(len(data))}),
            ]
        )
        dl = _make_downloader()
        part_path = tmp_path / "video.part.0"
        with patch("downloader.downloader.asyncio.sleep", new=AsyncMock()):
            result = await dl._download_segment(
                "https://cdn.example.com/v.mp4",
                part_path,
                0,
                len(data) - 1,
                MagicMock(),
            )
        assert result == len(data)
        assert part_path.read_bytes() == data

    @respx.mock
    async def test_200_raises_value_error(self, tmp_path: Path) -> None:
        """服务端返回 200 而非 206 → 抛 ValueError。"""
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=b"data")
        )
        dl = _make_downloader()
        part_path = tmp_path / "video.part.0"
        with pytest.raises(ValueError, match="200"):
            await dl._download_segment(
                "https://cdn.example.com/v.mp4", part_path, 0, 100, MagicMock()
            )

    @respx.mock
    async def test_network_error_retry_exhausted(self, tmp_path: Path) -> None:
        """网络异常重试耗尽 → 抛 httpx.HTTPError。"""
        respx.get("https://cdn.example.com/v.mp4").mock(
            side_effect=httpx.ConnectError("conn refused")
        )
        dl = _make_downloader()
        part_path = tmp_path / "video.part.0"
        with (
            patch("downloader.downloader.asyncio.sleep", new=AsyncMock()),
            pytest.raises(httpx.HTTPError),
        ):
            await dl._download_segment(
                "https://cdn.example.com/v.mp4",
                part_path,
                0,
                100,
                MagicMock(),
            )


# ==================== 分片下载：_merge_segments 测试 ====================


class TestMergeSegments:
    """_merge_segments 方法测试。"""

    def test_merge_two_parts(self, tmp_path: Path) -> None:
        """合并 2 个分片 → 最终文件包含拼接数据，.part 文件删除。"""
        part1 = tmp_path / "video.part.0"
        part2 = tmp_path / "video.part.1"
        final = tmp_path / "video.mp4"
        part1.write_bytes(b"hello ")
        part2.write_bytes(b"world")
        dl = _make_downloader()
        result = dl._merge_segments([part1, part2], final)
        assert result == str(final)
        assert final.read_bytes() == b"hello world"
        assert not part1.exists()
        assert not part2.exists()

    def test_merge_three_parts(self, tmp_path: Path) -> None:
        """合并 3 个分片 → 顺序正确，所有临时文件删除。"""
        part1 = tmp_path / "video.part.0"
        part2 = tmp_path / "video.part.1"
        part3 = tmp_path / "video.part.2"
        final = tmp_path / "video.mp4"
        part1.write_bytes(b"a")
        part2.write_bytes(b"b")
        part3.write_bytes(b"c")
        dl = _make_downloader()
        dl._merge_segments([part1, part2, part3], final)
        assert final.read_bytes() == b"abc"
        assert not part1.exists()
        assert not part2.exists()
        assert not part3.exists()

    def test_merge_overwrites_existing_final(self, tmp_path: Path) -> None:
        """最终文件已存在时覆盖旧内容。"""
        part1 = tmp_path / "video.part.0"
        final = tmp_path / "video.mp4"
        part1.write_bytes(b"new_content")
        final.write_bytes(b"old_data")
        dl = _make_downloader()
        dl._merge_segments([part1], final)
        assert final.read_bytes() == b"new_content"


# ==================== 分片下载：_download_segmented 测试 ====================


class TestDownloadSegmented:
    """_download_segmented 方法测试（分片并发下载）。"""

    @respx.mock
    async def test_all_segments_success(self, tmp_path: Path) -> None:
        """所有分片成功 → 合并文件，内容正确。"""
        total = 12 * 1024 * 1024
        data = b"x" * total

        def segment_response(request: httpx.Request) -> httpx.Response:
            range_header = request.headers.get("Range", "")
            range_spec = range_header.replace("bytes=", "")
            start_str, end_str = range_spec.split("-")
            start = int(start_str)
            end = int(end_str)
            chunk = data[start : end + 1]
            return httpx.Response(206, content=chunk, headers={"Content-Length": str(len(chunk))})

        respx.get("https://cdn.example.com/v.mp4").mock(side_effect=segment_response)
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme_seg")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme_seg.mp4"
        result = await dl._download_segmented(item, item.url, final_path, total)
        assert result.success is True
        assert result.local_path == str(final_path)
        assert final_path.exists()
        assert final_path.stat().st_size == total
        assert final_path.read_bytes() == data

    @respx.mock
    async def test_segment_failure_marks_failed(self, tmp_path: Path) -> None:
        """任一分片持续失败 → 标记 failed。"""
        total = 4 * 1024 * 1024  # 2 个分片
        respx.get("https://cdn.example.com/v.mp4").mock(return_value=httpx.Response(500))
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme_fail")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme_fail.mp4"
        with patch("downloader.downloader.asyncio.sleep", new=AsyncMock()):
            result = await dl._download_segmented(item, item.url, final_path, total)
        assert result.success is False
        assert "分片" in result.error
        assert _get_item_status(dl._conn, item.id) == "failed"

    @respx.mock
    async def test_progress_aggregation(self, tmp_path: Path) -> None:
        """ProgressReporter.update 被调用且聚合字节数正确。"""
        total = 4 * 1024 * 1024  # 2 个分片
        data = b"x" * total

        def segment_response(request: httpx.Request) -> httpx.Response:
            range_header = request.headers.get("Range", "")
            range_spec = range_header.replace("bytes=", "")
            start_str, end_str = range_spec.split("-")
            start = int(start_str)
            end = int(end_str)
            chunk = data[start : end + 1]
            return httpx.Response(206, content=chunk, headers={"Content-Length": str(len(chunk))})

        respx.get("https://cdn.example.com/v.mp4").mock(side_effect=segment_response)
        reporter = MagicMock(spec=ProgressReporter)
        reporter.update = MagicMock()
        conn = get_memory_connection()
        dl = _make_downloader(conn=conn, reporter=reporter)
        _, item = _make_downloader_with_item(
            download_dir=str(tmp_path), conn=conn, aweme_id="aweme_prog"
        )
        _insert_item(conn, item)
        final_path = tmp_path / "aweme_prog.mp4"
        await dl._download_segmented(item, item.url, final_path, total)
        assert reporter.update.called
        all_downloaded = [call.args[1] for call in reporter.update.call_args_list]
        assert max(all_downloaded) == total

    @respx.mock
    async def test_200_fallback_returns_error(self, tmp_path: Path) -> None:
        """分片返回 200 → 返回 FALLBACK_TO_SINGLE_STREAM。"""
        total = 4 * 1024 * 1024
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=b"data")
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme_fb")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme_fb.mp4"
        result = await dl._download_segmented(item, item.url, final_path, total)
        assert result.success is False
        assert result.error == "FALLBACK_TO_SINGLE_STREAM"


# ==================== 分片下载：_download_single_file 集成测试 ====================


class TestDownloadSingleFileSegmented:
    """_download_single_file 分片下载集成测试。"""

    @respx.mock
    async def test_large_file_uses_segmented(self, tmp_path: Path) -> None:
        """大文件（≥10MB）走分片下载路径。"""
        total = 15 * 1024 * 1024
        data = b"x" * total
        respx.head("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, headers={"Content-Length": str(total)})
        )

        def segment_response(request: httpx.Request) -> httpx.Response:
            range_header = request.headers.get("Range", "")
            range_spec = range_header.replace("bytes=", "")
            start_str, end_str = range_spec.split("-")
            start = int(start_str)
            end = int(end_str)
            chunk = data[start : end + 1]
            return httpx.Response(206, content=chunk, headers={"Content-Length": str(len(chunk))})

        get_route = respx.get("https://cdn.example.com/v.mp4").mock(side_effect=segment_response)
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme_large")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme_large.mp4"
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True
        assert final_path.exists()
        assert final_path.stat().st_size == total
        # 分片路径产生 8 个 GET 请求（15MB / 2MB = 8 片）
        assert get_route.call_count == 8

    @respx.mock
    async def test_small_file_uses_single_stream(self, tmp_path: Path) -> None:
        """小文件（<10MB）走单流下载路径。"""
        total = 5 * 1024 * 1024
        data = b"x" * total
        respx.head("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, headers={"Content-Length": str(total)})
        )
        get_route = respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=data, headers={"Content-Length": str(total)})
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme_small")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme_small.mp4"
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True
        assert final_path.exists()
        assert final_path.read_bytes() == data
        # 单流路径仅 1 个 GET 请求
        assert get_route.call_count == 1
        # 确认未创建 .part.{i} 分片文件
        for i in range(MAX_SEGMENTS):
            assert not (tmp_path / f"aweme_small.mp4.part.{i}").exists()

    @respx.mock
    async def test_head_failure_falls_back_to_single_stream(self, tmp_path: Path) -> None:
        """HEAD 请求失败 → 回退到单流下载。"""
        data = b"single_stream_data"
        respx.head("https://cdn.example.com/v.mp4").mock(side_effect=httpx.ConnectError("conn"))
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=data)
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme_headfail")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme_headfail.mp4"
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True
        assert final_path.read_bytes() == data

    @respx.mock
    async def test_fallback_to_single_stream(self, tmp_path: Path) -> None:
        """分片返回 200 触发回退 → 走单流下载。"""
        total = 15 * 1024 * 1024
        respx.head("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, headers={"Content-Length": str(total)})
        )
        respx.get("https://cdn.example.com/v.mp4").mock(
            return_value=httpx.Response(200, content=b"fallback_data")
        )
        dl, item = _make_downloader_with_item(download_dir=str(tmp_path), aweme_id="aweme_fb2")
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme_fb2.mp4"
        result = await dl._download_single_file(item, item.url, final_path)
        assert result.success is True
        assert final_path.read_bytes() == b"fallback_data"


# ==================== WebP 自动转码测试（ISSUE-20） ====================


class TestWebPConvert:
    """WebP 自动转码为 MP4 功能测试。"""

    def test_webp_in_extensions(self) -> None:
        """.webp 在参与转码的扩展名集合中。"""
        assert ".webp" in WEBP_EXTENSIONS

    def test_mp4_extension_constant(self) -> None:
        """转码目标扩展名为 .mp4。"""
        assert MP4_EXTENSION == ".mp4"

    def test_convert_not_called_for_mp4(self, tmp_path: Path) -> None:
        """非 WebP 内容的 .mp4 文件不触发转码。"""
        dl = _make_downloader(webp_auto_convert=True)
        mp4 = tmp_path / "video.mp4"
        mp4.write_bytes(b"not a webp file")
        with patch.object(Downloader, "_convert_webp_to_mp4") as mock_convert:
            result = dl._maybe_convert_webp(str(mp4))
            mock_convert.assert_not_called()
            assert result == str(mp4)

    def test_convert_skipped_when_disabled(self, tmp_path: Path) -> None:
        """关闭开关时 .webp 文件不转码。"""
        dl = _make_downloader(webp_auto_convert=False)
        webp = tmp_path / "image.webp"
        webp.write_bytes(b"data")
        with patch.object(Downloader, "_convert_webp_to_mp4") as mock_convert:
            result = dl._maybe_convert_webp(str(webp))
            mock_convert.assert_not_called()
            assert result == str(webp)

    def test_convert_called_for_webp(self, tmp_path: Path) -> None:
        """开启开关且文件为真正的 WebP（魔数检测）时触发转码。"""
        dl = _make_downloader(webp_auto_convert=True)
        webp = tmp_path / "image.webp"
        # 写入真实 WebP 魔数（RIFF....WEBP）
        webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        mp4 = tmp_path / "image.mp4"
        with patch.object(
            Downloader, "_convert_webp_to_mp4", return_value=str(mp4)
        ) as mock_convert:
            result = dl._maybe_convert_webp(str(webp))
            mock_convert.assert_called_once_with(str(webp))
            assert result == str(mp4)

    def test_convert_failure_keeps_original(self, tmp_path: Path) -> None:
        """转码失败时保留原 WebP 文件路径。"""
        dl = _make_downloader(webp_auto_convert=True)
        webp = tmp_path / "image.webp"
        webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        with patch.object(Downloader, "_convert_webp_to_mp4", return_value=None) as mock_convert:
            result = dl._maybe_convert_webp(str(webp))
            mock_convert.assert_called_once()
            assert result == str(webp)

    def test_convert_webp_to_mp4_ffmpeg_missing(self, tmp_path: Path) -> None:
        """FFmpeg 不可用时返回 None。"""
        with patch.object(Downloader, "_find_ffmpeg", return_value=None):
            result = Downloader._convert_webp_to_mp4(str(tmp_path / "image.webp"))
            assert result is None

    def test_convert_webp_to_mp4_success(self, tmp_path: Path) -> None:
        """Pillow 拆帧 + FFmpeg 编码成功时返回 MP4 路径，原 WebP 保留。"""
        webp = tmp_path / "image.webp"
        webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        mp4 = tmp_path / "image.mp4"
        mock_img = MagicMock()
        mock_img.n_frames = 1
        mock_img.info = {"duration": 100}
        with (
            patch.object(Downloader, "_find_ffmpeg", return_value="ffmpeg"),
            patch("PIL.Image.open", return_value=mock_img),
            patch(
                "downloader.downloader.subprocess.run",
                return_value=MagicMock(returncode=0, stderr=b""),
            ),
        ):
            result = Downloader._convert_webp_to_mp4(str(webp))
        assert result == str(mp4)
        # 原 WebP 文件保留
        assert webp.exists()

    def test_convert_webp_to_mp4_failure_keeps_original(self, tmp_path: Path) -> None:
        """转码失败时保留原 WebP 文件并返回 None。"""
        webp = tmp_path / "image.webp"
        webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        mock_img = MagicMock()
        mock_img.n_frames = 1
        mock_img.info = {"duration": 100}
        with (
            patch.object(Downloader, "_find_ffmpeg", return_value="ffmpeg"),
            patch("PIL.Image.open", return_value=mock_img),
            patch(
                "downloader.downloader.subprocess.run",
                return_value=MagicMock(returncode=1, stderr=b"error"),
            ),
        ):
            result = Downloader._convert_webp_to_mp4(str(webp))
        assert result is None
        assert webp.exists()

    def test_convert_skips_if_mp4_exists(self, tmp_path: Path) -> None:
        """同名的 MP4 已存在时跳过转码。"""
        webp = tmp_path / "image.webp"
        webp.write_bytes(b"webpdata")
        mp4 = tmp_path / "image.mp4"
        mp4.write_bytes(b"existing")
        with (
            patch.object(Downloader, "_find_ffmpeg", return_value="ffmpeg"),
            patch("downloader.downloader.subprocess.run") as mock_run,
        ):
            result = Downloader._convert_webp_to_mp4(str(webp))
        mock_run.assert_not_called()
        assert result == str(mp4)
        assert webp.exists()

    @respx.mock
    async def test_download_webp_auto_converts(self, tmp_path: Path) -> None:
        """下载 .webp 文件后自动转码，local_path 更新为 .mp4。"""
        respx.head("https://cdn.example.com/img.webp").mock(return_value=httpx.Response(404))
        data = b"webp_binary_data"
        respx.get("https://cdn.example.com/img.webp").mock(
            return_value=httpx.Response(200, content=data)
        )
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id="aweme_webp",
            url="https://cdn.example.com/img.webp",
            webp_auto_convert=True,
        )
        _insert_item(dl._conn, item)
        final_path = tmp_path / "aweme_webp.webp"
        with patch.object(
            Downloader,
            "_maybe_convert_webp",
            side_effect=lambda p: str(Path(p).with_suffix(".mp4")),
        ) as mock_convert:
            result = await dl._download_single_file(item, item.url, final_path)
            mock_convert.assert_called_once()
        assert result.success is True
        assert result.local_path == str(tmp_path / "aweme_webp.mp4")
        assert _get_item_local_path(dl._conn, item.id) == str(tmp_path / "aweme_webp.mp4")
