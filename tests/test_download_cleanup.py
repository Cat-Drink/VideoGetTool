"""审计 M13/S3：HLS 播放列表检测与 .part/产物清理单测。"""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import MagicMock

import httpx
import pytest

from downloader.cleanup import (
    safe_remove_output,
    sweep_orphan_part_files,
)
from downloader.downloader import Downloader, PlaylistContentError


class TestPlaylistDetection:
    """M13：下载内容为 HLS 播放列表时必须中止而非保存。"""

    def test_is_playlist_content_markers(self):
        """魔数 #EXTM3U / #EXT-X- 命中。"""
        assert Downloader._is_playlist_content(b"#EXTM3U\n...") is True
        assert Downloader._is_playlist_content(b"#EXT-X-TARGETDURATION:6\n") is True
        assert Downloader._is_playlist_content(b"#EXTM3U8") is True

    def test_media_headers_not_playlist(self):
        """真实媒体头不误报。"""
        assert Downloader._is_playlist_content(b"\x00\x00\x00\x18ftypmp42") is False
        assert Downloader._is_playlist_content(b"\xff\xd8\xff\xe0JFIF") is False
        assert Downloader._is_playlist_content(b"RIFFxxxxWEBPVP8 ") is False

    @pytest.mark.asyncio
    async def test_stream_to_file_raises_on_playlist(self, tmp_path):
        """_stream_to_file 首块命中魔数 → PlaylistContentError，不写文件。"""
        # 用 __new__ 绕过 __init__ 依赖；静态方法 _is_playlist_content 可直用
        dl = Downloader.__new__(Downloader)

        response = MagicMock(spec=httpx.Response)

        async def fake_chunks(size: int = 65536):
            yield b"#EXTM3U\n#EXT-X-VERSION:3\n"

        response.aiter_bytes = fake_chunks
        part = tmp_path / "x.mp4.part"
        task_item = MagicMock(id=1)
        with pytest.raises(PlaylistContentError):
            await Downloader._stream_to_file(
                dl, response, part, task_item, 0, 0, report_progress=False
            )
        assert not part.exists()

    @pytest.mark.asyncio
    async def test_download_single_file_playlist_content_type(self, tmp_path):
        """Content-Type 命中 mpegurl → 不重试直接失败并清理 .part。"""
        dl = Downloader.__new__(Downloader)
        dl._http_client = MagicMock()
        dl._mark_status = MagicMock()
        dl._item_repo = MagicMock()
        dl._progress_reporter = MagicMock()
        dl._file_locks = {}
        dl._bili_reparser = None
        dl._video_parser = None
        dl._cookie_repository = None
        dl._ffmpeg_path = None
        dl._semaphore = asyncio.Semaphore(2)

        # 预写一个 .part（模拟已有残留），成功后应被清理
        part = tmp_path / "x.mp4.part"
        part.write_bytes(b"partial")
        final = tmp_path / "x.mp4"

        class _Resp:
            headers = {"Content-Type": "application/vnd.apple.mpegurl"}
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        async def fake_get_file_size(url, headers=None):
            return None

        dl._get_file_size = fake_get_file_size
        dl._get_part_path = MagicMock(return_value=part)
        dl._get_final_path = MagicMock(return_value=final)
        dl._get_download_headers = MagicMock(return_value={})
        dl._should_retry = MagicMock(return_value=False)
        dl._http_client.stream.return_value = _Resp()

        result = await Downloader._download_single_file(
            dl,
            task_item=MagicMock(id=9, retry_count=0),
            url="https://x/y.m4s",
            final_path=final,
        )
        assert result.success is False
        assert "HLS" in (result.error or "") or "播放列表" in (result.error or "")
        assert not part.exists()


class TestCleanup:
    """S3：产物安全删除（含目录包含性校验）+ 孤儿 .part 清理。"""

    def test_safe_remove_contained_file(self, tmp_path):
        f = tmp_path / "out.mp4"
        f.write_bytes(b"x")
        part = tmp_path / "out.mp4.part"
        part.write_bytes(b"p")
        assert safe_remove_output(f, tmp_path) is True
        assert not f.exists()
        assert not part.exists()

    def test_safe_remove_missing_file_returns_true(self, tmp_path):
        assert safe_remove_output(tmp_path / "ghost.mp4", tmp_path) is True

    def test_safe_remove_outside_base_refused(self, tmp_path):
        outside = tmp_path.parent / "evil.bat"
        outside.write_bytes(b"x")
        try:
            assert safe_remove_output(outside, tmp_path) is False
            assert outside.exists()  # 越界不删
        finally:
            outside.unlink(missing_ok=True)

    def test_safe_remove_directory(self, tmp_path):
        d = tmp_path / "image_set_dir"
        d.mkdir()
        (d / "1.jpg").write_bytes(b"x")
        assert safe_remove_output(d, tmp_path) is True
        assert not d.exists()

    def test_sweep_orphan_parts_removes_old_only(self, tmp_path):
        fresh = tmp_path / "fresh.mp4.part"
        fresh.write_bytes(b"new")
        stale = tmp_path / "stale.mp4.part"
        stale.write_bytes(b"old")
        old_ts = time.time() - 8 * 86400
        os.utime(stale, (old_ts, old_ts))

        removed = sweep_orphan_part_files(tmp_path, max_age_days=7)
        assert removed == 1
        assert stale.exists() is False
        assert fresh.exists() is True  # 新文件保留

    def test_sweep_non_existent_dir_returns_zero(self, tmp_path):
        assert sweep_orphan_part_files(tmp_path / "nope") == 0
