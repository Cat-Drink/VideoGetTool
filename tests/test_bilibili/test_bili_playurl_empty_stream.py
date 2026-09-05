"""B 站播放流解析的 S4 空流跳过与全空报错单测。

覆盖 v2 指南 §5.8（P1-8）：
    1. base_url/backup_url 均为空 → 视频/音频流被跳过（不再 append 空 URL 流）
    2. backup_url 为空列表 → 不回退成 ""（旧的 "backup_url[0] or ''" 脆弱写法）
    3. DASH 响应解析后全空 → 抛 VideoNotFoundError（而非静默返回空流）
    4. 正常流不受影响（base_url 或 backup_url[0] 正常取值）
"""

from __future__ import annotations

import pytest

from crawlers.bilibili.bili_video_parser import BiliVideoParser
from crawlers.exceptions import VideoNotFoundError

pytestmark = pytest.mark.bilibili


class TestParsePlayurlResponseEmptyStream:
    """_parse_playurl_response 空流跳过（S4/P1-8）。"""

    def test_skip_video_stream_without_url_and_backup(self) -> None:
        """视频流 base_url 与 backup_url 均缺失 → 跳过而非 append 空 URL。"""
        data = {
            "dash": {
                "video": [{"id": 1, "codecs": "avc1", "bandwidth": 1000}],
                "audio": [{"id": 30216, "base_url": "https://upos.example.com/audio.mp4"}],
            }
        }
        result = BiliVideoParser._parse_playurl_response(data, "BV1xx", 123, 80)
        assert result.video_streams == []
        assert len(result.audio_streams) == 1
        assert result.audio_streams[0].url == "https://upos.example.com/audio.mp4"

    def test_skip_video_stream_with_empty_backup_list(self) -> None:
        """backup_url 为空列表时不再回退成 ""（旧的脆弱写法）。"""
        data = {
            "dash": {
                "video": [
                    {"id": 1, "backup_url": [], "codecs": "avc1", "bandwidth": 1000},
                    {"id": 2, "base_url": "https://upos.example.com/v2.mp4"},
                ],
                "audio": [],
            }
        }
        result = BiliVideoParser._parse_playurl_response(data, "BV1xx", 123, 80)
        assert len(result.video_streams) == 1
        assert result.video_streams[0].id == 2
        assert result.video_streams[0].url == "https://upos.example.com/v2.mp4"

    def test_use_backup_url_when_base_missing(self) -> None:
        """base_url 缺失但 backup_url 有值 → 取 backup_url[0]。"""
        data = {
            "dash": {
                "video": [{"id": 7, "backup_url": ["https://upos.example.com/backup.mp4"]}],
                "audio": [],
            }
        }
        result = BiliVideoParser._parse_playurl_response(data, "BV1xx", 123, 80)
        assert len(result.video_streams) == 1
        assert result.video_streams[0].url == "https://upos.example.com/backup.mp4"
        assert result.video_streams[0].base_url == "https://upos.example.com/backup.mp4"

    def test_skip_audio_stream_without_url(self) -> None:
        """音频流空 URL → 跳过。"""
        data = {
            "dash": {
                "video": [{"id": 1, "base_url": "https://upos.example.com/v.mp4"}],
                "audio": [
                    {"id": 30216, "backup_url": [""]},
                    {"id": 30232, "base_url": "https://upos.example.com/a2.mp4"},
                ],
            }
        }
        result = BiliVideoParser._parse_playurl_response(data, "BV1xx", 123, 80)
        assert len(result.audio_streams) == 1
        assert result.audio_streams[0].id == 30232

    def test_raise_when_dash_all_empty(self) -> None:
        """DASH 响应存在但解析后视频/音频全空 → 明确报错。"""
        data = {
            "dash": {
                "video": [{"id": 1, "backup_url": []}],
                "audio": [{"id": 2, "backup_url": []}],
            }
        }
        with pytest.raises(VideoNotFoundError):
            BiliVideoParser._parse_playurl_response(data, "BV1xx", 123, 80)

    def test_normal_dash_streams_unchanged(self) -> None:
        """正常 DASH 双流不受影响。"""
        data = {
            "dash": {
                "video": [{"id": 1, "base_url": "https://upos.example.com/v.mp4", "width": 1920}],
                "audio": [{"id": 30216, "base_url": "https://upos.example.com/a.mp4"}],
            },
            "quality": 80,
            "quality_name": "1080P",
            "timelength": 300000,
        }
        result = BiliVideoParser._parse_playurl_response(data, "BV1xx", 123, 80)
        assert result.dash is True
        assert len(result.video_streams) == 1
        assert result.video_streams[0].url == "https://upos.example.com/v.mp4"
        assert len(result.audio_streams) == 1
        assert result.quality == 80
        assert result.duration == 300

    def test_non_dash_durl_unchanged(self) -> None:
        """非 DASH（durl）单一直链不受影响。"""
        data = {"durl": [{"url": "https://upos.example.com/video.flv"}]}
        result = BiliVideoParser._parse_playurl_response(data, "BV1xx", 123, 80)
        assert result.dash is False
        assert result.url == "https://upos.example.com/video.flv"
        assert result.video_streams == []
