"""VideoParser 单元测试。

覆盖场景:
    - parse_video 主流程（普通视频/图集/长视频/已删除视频）
    - 无水印直链 playwm→play 替换与不替换
    - 图集 images 为空列表
    - 标签提取
    - HTTP 层异常传播（CookieInvalid/RateLimited/VerifyRequired/Network）
    - 时长格式化、类型判断纯单元测试

测试通过 AsyncMock + MagicMock 模拟 HttpClient，不打真实网络。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from crawlers.exceptions import (
    CookieInvalidError,
    NetworkError,
    RateLimitedError,
    VerifyRequiredError,
    VideoNotFoundError,
)
from crawlers.video_parser import VideoInfo, VideoParser

# ==================== fixtures ====================


@pytest.fixture
def mock_http_client() -> MagicMock:
    """返回 mock HttpClient，get 方法为 AsyncMock 供 await 调用。"""
    client = MagicMock(name="HttpClient")
    client.get = AsyncMock(name="HttpClient.get")
    return client


@pytest.fixture
def mock_signer() -> MagicMock:
    """返回 mock Signer（VideoParser 不直接调用，占位注入）。"""
    return MagicMock(name="Signer")


@pytest.fixture
def video_parser(mock_http_client: MagicMock, mock_signer: MagicMock) -> VideoParser:
    """返回注入 mock 的 VideoParser 实例。"""
    return VideoParser(mock_http_client, mock_signer)


def _make_response(payload: dict, status_code: int = 200) -> httpx.Response:
    """构造 JSON 响应 httpx.Response。"""
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("GET", "https://www.douyin.com/aweme/v1/web/aweme/detail/"),
    )


def _normal_video_detail() -> dict:
    """构造普通视频的 aweme_detail 节点（含 playwm 水印标记）。"""
    return {
        "aweme_id": "7000000000000000001",
        "desc": "测试普通视频 #funny #test",
        "create_time": 1700000000,
        "aweme_type": 0,
        "author": {"nickname": "测试作者", "sec_uid": "sec_uid_author_001"},
        "video": {
            "duration": 15000,
            "play_addr": {"url_list": ["https://v.douyin.com/playwm/abc123/video.mp4"]},
            "cover": {"url_list": ["https://p.douyinpic.com/cover.jpg"]},
        },
        "statistics": {
            "digg_count": 1234,
            "comment_count": 56,
            "share_count": 7,
            "collect_count": 89,
        },
        "text_extra": [
            {"hashtag_name": "funny"},
            {"hashtag_name": "test"},
            {"hashtag_name": ""},
            {},  # 无 hashtag_name 字段
        ],
    }


def _long_video_detail() -> dict:
    """构造长视频（duration ≥ 30 分钟）的 aweme_detail 节点。"""
    return {
        "aweme_id": "7000000000000000002",
        "desc": "测试长视频",
        "create_time": 1700000100,
        "author": {"nickname": "长视频作者", "sec_uid": "sec_uid_long_002"},
        "video": {
            # v0.1.3：长视频阈值改为 ≥ 30 分钟（1800000 毫秒）
            "duration": 1800000,  # 30:00
            "play_addr": {"url_list": ["https://v.douyin.com/play/long.mp4"]},
            "cover": {"url_list": ["https://p.douyinpic.com/long_cover.jpg"]},
        },
        "statistics": {
            "digg_count": 9999,
            "comment_count": 100,
            "share_count": 50,
            "collect_count": 5,
        },
    }


def _image_set_detail() -> dict:
    """构造图集的 aweme_detail 节点。"""
    return {
        "aweme_id": "7000000000000000003",
        "desc": "测试图集",
        "create_time": 1700000200,
        "author": {"nickname": "图集作者", "sec_uid": "sec_uid_image_003"},
        "video": {
            "duration": 0,
            "cover": {"url_list": ["https://p.douyinpic.com/img_cover.jpg"]},
        },
        "images": [
            {"url_list": ["https://p.douyinpic.com/img1.jpg"]},
            {"url_list": ["https://p.douyinpic.com/img2.jpg"]},
            {"url_list": ["https://p.douyinpic.com/img3.jpg"]},
        ],
        "statistics": {"digg_count": 10, "comment_count": 2, "share_count": 0, "collect_count": 1},
        "text_extra": [],
    }


# ==================== parse_video 主流程测试 ====================


class TestParseVideo:
    """parse_video 主流程测试。"""

    async def test_parse_normal_video(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """正常视频解析：type='video'，无水印直链 playwm→play 替换，图集为空。"""
        mock_http_client.get.return_value = _make_response(
            {"status_code": 0, "aweme_detail": _normal_video_detail()}
        )
        info = await video_parser.parse_video("7000000000000000001", "ttwid=fake")
        assert isinstance(info, VideoInfo)
        assert info.aweme_id == "7000000000000000001"
        assert info.type == "video"
        assert info.title == "测试普通视频 #funny #test"
        assert info.author == "测试作者"
        assert info.author_sec_id == "sec_uid_author_001"
        assert info.duration == "15s"
        assert info.cover_url == "https://p.douyinpic.com/cover.jpg"
        # playwm → play 替换
        assert info.no_watermark_url == "https://v.douyin.com/play/abc123/video.mp4"
        assert "playwm" not in (info.no_watermark_url or "")
        assert info.image_urls == []
        assert info.publish_time == "2023-11-14T22:13:20Z"
        assert info.like_count == 1234
        assert info.comment_count == 56
        assert info.share_count == 7
        assert info.collect_count == 89
        assert info.tags == ["funny", "test"]
        assert info.raw_json["aweme_id"] == "7000000000000000001"
        # 验证调用参数：use_cookie_pool=False + 显式 cookie
        mock_http_client.get.assert_awaited_once()
        call_args = mock_http_client.get.await_args
        assert call_args.kwargs["use_cookie_pool"] is False
        assert call_args.kwargs["cookie"] == "ttwid=fake"
        assert call_args.kwargs["params"]["aweme_id"] == "7000000000000000001"

    async def test_parse_image_set(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """图集解析：type='image_set'，image_urls 非空，no_watermark_url=None，duration=None。"""
        mock_http_client.get.return_value = _make_response(
            {"status_code": 0, "aweme_detail": _image_set_detail()}
        )
        info = await video_parser.parse_video("7000000000000000003", "ttwid=fake")
        assert info.type == "image_set"
        assert info.no_watermark_url is None
        assert info.duration is None
        assert info.image_urls == [
            "https://p.douyinpic.com/img1.jpg",
            "https://p.douyinpic.com/img2.jpg",
            "https://p.douyinpic.com/img3.jpg",
        ]

    async def test_parse_long_video(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """长视频解析（duration ≥ 30 分钟）：type='long_video'，duration 显示 'MM:SS'。"""
        mock_http_client.get.return_value = _make_response(
            {"status_code": 0, "aweme_detail": _long_video_detail()}
        )
        info = await video_parser.parse_video("7000000000000000002", "ttwid=fake")
        assert info.type == "long_video"
        assert info.duration == "30:00"
        assert info.no_watermark_url == "https://v.douyin.com/play/long.mp4"
        assert info.image_urls == []

    async def test_parse_deleted_video(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """已删除视频：status_code != 0 → VideoNotFoundError。"""
        mock_http_client.get.return_value = _make_response(
            {"status_code": 1, "status_msg": "aweme not found"}
        )
        with pytest.raises(VideoNotFoundError, match="aweme not found"):
            await video_parser.parse_video("9999999999999999999", "ttwid=fake")

    async def test_parse_aweme_detail_missing(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """aweme_detail 字段缺失 → VideoNotFoundError。"""
        mock_http_client.get.return_value = _make_response({"status_code": 0})
        with pytest.raises(VideoNotFoundError, match="aweme_detail 缺失"):
            await video_parser.parse_video("7000000000000000001", "ttwid=fake")

    async def test_parse_response_not_json(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """响应非 JSON（json() 抛 ValueError）→ VideoNotFoundError。"""
        response = MagicMock(spec=httpx.Response)
        response.json.side_effect = ValueError("not json")
        mock_http_client.get.return_value = response
        with pytest.raises(VideoNotFoundError, match="非 JSON"):
            await video_parser.parse_video("7000000000000000001", "ttwid=fake")

    async def test_parse_status_code_nonzero_no_status_msg(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """status_code != 0 且无 status_msg → 使用默认"未知错误"。"""
        mock_http_client.get.return_value = _make_response({"status_code": 9})
        with pytest.raises(VideoNotFoundError, match="未知错误"):
            await video_parser.parse_video("7000000000000000001", "ttwid=fake")


# ==================== 无水印/图集提取测试 ====================


class TestExtractUrls:
    """无水印直链与图集 URL 提取测试。"""

    def test_no_watermark_url_playwm_replace(self) -> None:
        """含 playwm 的 URL 被替换为 play。"""
        detail = {"video": {"play_addr": {"url_list": ["https://x/playwm/a.mp4"]}}}
        assert VideoParser._extract_no_watermark_url(detail) == "https://x/play/a.mp4"

    def test_no_watermark_url_no_playwm(self) -> None:
        """不含 playwm 的 URL 原样返回。"""
        detail = {"video": {"play_addr": {"url_list": ["https://x/play/a.mp4"]}}}
        assert VideoParser._extract_no_watermark_url(detail) == "https://x/play/a.mp4"

    def test_no_watermark_url_empty_list(self) -> None:
        """url_list 为空 → None。"""
        detail = {"video": {"play_addr": {"url_list": []}}}
        assert VideoParser._extract_no_watermark_url(detail) is None

    def test_no_watermark_url_missing_field(self) -> None:
        """play_addr 字段缺失 → None。"""
        assert VideoParser._extract_no_watermark_url({}) is None

    def test_no_watermark_url_skips_webp_url(self) -> None:
        """play_addr 混入 WebP 封面直链时跳过，返回真实视频 URL。"""
        detail = {
            "video": {
                "play_addr": {
                    "url_list": [
                        "https://x/cover.webp?mime_type=image_webp",
                        "https://x/play/a.mp4",
                    ]
                }
            }
        }
        assert VideoParser._extract_no_watermark_url(detail) == "https://x/play/a.mp4"

    def test_no_watermark_url_all_webp(self) -> None:
        """play_addr.url_list 全部为 WebP 且无 bit_rate/download_addr → None。"""
        detail = {
            "video": {
                "play_addr": {
                    "url_list": ["https://x/cover.webp?mime_type=image_webp"]
                }
            }
        }
        assert VideoParser._extract_no_watermark_url(detail) is None

    def test_no_watermark_url_prefers_bit_rate(self) -> None:
        """play_addr 为 WebP 封面时，优先从 bit_rate 提取真实视频直链。"""
        detail = {
            "video": {
                "bit_rate": [
                    {"play_addr": {"url_list": ["https://x/br/webm?mime_type=video_mp4"]}}
                ],
                "download_addr": {"url_list": ["https://x/dl/a.mp4"]},
                "play_addr": {"url_list": ["https://x/cover.webp?mime_type=image_webp"]},
            }
        }
        assert (
            VideoParser._extract_no_watermark_url(detail)
            == "https://x/br/webm?mime_type=video_mp4"
        )

    def test_no_watermark_url_bit_rate_skips_webp(self) -> None:
        """bit_rate 某档位为 WebP 时跳过，继续下一档位。"""
        detail = {
            "video": {
                "bit_rate": [
                    {"play_addr": {"url_list": ["https://x/br/cover.webp"]}},
                    {"play_addr": {"url_list": ["https://x/br/a.mp4"]}},
                ],
                "play_addr": {"url_list": ["https://x/cover.webp"]},
            }
        }
        assert VideoParser._extract_no_watermark_url(detail) == "https://x/br/a.mp4"

    def test_no_watermark_url_falls_back_to_download_addr(self) -> None:
        """bit_rate 无可用时回退 download_addr。"""
        detail = {
            "video": {
                "bit_rate": None,
                "download_addr": {
                    "url_list": ["https://x/dl/playwm/b.webm?mime_type=video_mp4"]
                },
                "play_addr": {"url_list": ["https://x/cover.webp"]},
            }
        }
        assert (
            VideoParser._extract_no_watermark_url(detail)
            == "https://x/dl/play/b.webm?mime_type=video_mp4"
        )

    def test_no_watermark_url_bit_rate_absent_use_play_addr(self) -> None:
        """bit_rate / download_addr 均缺失时使用 play_addr。"""
        detail = {"video": {"play_addr": {"url_list": ["https://x/play/a.mp4"]}}}
        assert VideoParser._extract_no_watermark_url(detail) == "https://x/play/a.mp4"

    def test_extract_image_urls_empty(self) -> None:
        """images 为空列表 → 返回空列表。"""
        assert VideoParser._extract_image_urls({"images": []}) == []

    def test_extract_image_urls_missing(self) -> None:
        """images 字段缺失 → 返回空列表。"""
        assert VideoParser._extract_image_urls({}) == []

    def test_extract_image_urls_skips_empty_url_list(self) -> None:
        """单张图片 url_list 为空时跳过该项。"""
        detail = {
            "images": [
                {"url_list": ["https://x/1.jpg"]},
                {"url_list": []},
                {"url_list": ["https://x/3.jpg"]},
            ]
        }
        assert VideoParser._extract_image_urls(detail) == [
            "https://x/1.jpg",
            "https://x/3.jpg",
        ]


# ==================== 标签提取测试 ====================


class TestExtractTags:
    """标签提取测试。"""

    def test_extract_tags_normal(self) -> None:
        """正常提取多个标签。"""
        detail = {
            "text_extra": [
                {"hashtag_name": "funny"},
                {"hashtag_name": "test"},
            ]
        }
        assert VideoParser._extract_tags(detail) == ["funny", "test"]

    def test_extract_tags_empty(self) -> None:
        """text_extra 为空列表 → 空列表。"""
        assert VideoParser._extract_tags({"text_extra": []}) == []

    def test_extract_tags_missing(self) -> None:
        """text_extra 缺失 → 空列表。"""
        assert VideoParser._extract_tags({}) == []

    def test_extract_tags_skips_empty_name(self) -> None:
        """hashtag_name 为空字符串时跳过。"""
        detail = {"text_extra": [{"hashtag_name": ""}, {"hashtag_name": "real"}]}
        assert VideoParser._extract_tags(detail) == ["real"]


# ==================== 异常传播测试 ====================


class TestExceptionPropagation:
    """HTTP 层异常（由 HttpClient 抛出）应原样传播。"""

    async def test_cookie_invalid_raises(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """HTTP 461 → CookieInvalidError 传播。"""
        mock_http_client.get.side_effect = CookieInvalidError("Cookie 失效")
        with pytest.raises(CookieInvalidError):
            await video_parser.parse_video("1", "ttwid=fake")

    async def test_rate_limited_raises(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """HTTP 429 → RateLimitedError 传播。"""
        mock_http_client.get.side_effect = RateLimitedError("限流")
        with pytest.raises(RateLimitedError):
            await video_parser.parse_video("1", "ttwid=fake")

    async def test_verify_required_raises(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """验证 HTML → VerifyRequiredError 传播。"""
        mock_http_client.get.side_effect = VerifyRequiredError("需验证")
        with pytest.raises(VerifyRequiredError):
            await video_parser.parse_video("1", "ttwid=fake")

    async def test_network_error_raises(
        self, video_parser: VideoParser, mock_http_client: MagicMock
    ) -> None:
        """网络异常 → NetworkError 传播。"""
        mock_http_client.get.side_effect = NetworkError("连接失败")
        with pytest.raises(NetworkError):
            await video_parser.parse_video("1", "ttwid=fake")


# ==================== 纯单元测试：时长格式化与类型判断 ====================


class TestFormatDuration:
    """_format_duration 时长格式化测试。"""

    def test_format_duration_short(self) -> None:
        """< 60 秒 → 'Xs' 格式。"""
        assert VideoParser._format_duration(15000) == "15s"

    def test_format_duration_long(self) -> None:
        """≥ 60 秒 → 'MM:SS' 格式。"""
        assert VideoParser._format_duration(750000) == "12:30"

    def test_format_duration_exactly_60s(self) -> None:
        """正好 60 秒 → '1:00'。"""
        assert VideoParser._format_duration(60000) == "1:00"

    def test_format_duration_zero(self) -> None:
        """0 毫秒 → '0s'。"""
        assert VideoParser._format_duration(0) == "0s"

    def test_format_duration_over_hour(self) -> None:
        """超过 1 小时仍按 MM:SS 展示（如 90:15）。"""
        assert VideoParser._format_duration(5415000) == "90:15"


class TestDetectVideoType:
    """_detect_video_type 类型判断测试。"""

    def test_detect_type_image_set(self) -> None:
        """images 非空 → 'image_set'。"""
        assert VideoParser._detect_video_type({"images": [{"url_list": ["x"]}]}) == "image_set"

    def test_detect_type_long_video(self) -> None:
        """v0.1.3：duration ≥ 1800000 毫秒（≥ 30 分钟） → 'long_video'。"""
        assert VideoParser._detect_video_type({"video": {"duration": 1860000}}) == "long_video"

    def test_detect_type_video(self) -> None:
        """普通视频（无 images，duration < 30 分钟）→ 'video'。"""
        assert VideoParser._detect_video_type({"video": {"duration": 15000}}) == "video"

    def test_detect_type_empty_detail(self) -> None:
        """空 detail → 'video'（兜底）。"""
        assert VideoParser._detect_video_type({}) == "video"

    def test_detect_type_empty_images_list(self) -> None:
        """images 为空列表 → 进入 duration 判断分支。"""
        assert VideoParser._detect_video_type({"images": [], "video": {"duration": 1800000}}) == (
            "long_video"
        )

    def test_detect_type_duration_exactly_threshold(self) -> None:
        """v0.1.3：duration 恰为 30 分钟（1800000 毫秒）→ 'long_video'（`>=` 阈值）。"""
        assert VideoParser._detect_video_type({"video": {"duration": 1800000}}) == "long_video"

    def test_detect_type_duration_below_threshold(self) -> None:
        """v0.1.3：duration 为 29 分钟（1740000 毫秒）→ 'video'。"""
        assert VideoParser._detect_video_type({"video": {"duration": 1740000}}) == "video"

    def test_detect_type_duration_above_threshold(self) -> None:
        """v0.1.3：duration 为 31 分钟（1860000 毫秒）→ 'long_video'。"""
        assert VideoParser._detect_video_type({"video": {"duration": 1860000}}) == "long_video"

    def test_detect_type_image_set_not_affected_by_duration(self) -> None:
        """v0.1.3：图集即使 duration ≥ 30 分钟仍为 'image_set'（图集判定优先）。"""
        detail = {
            "images": [{"url_list": ["x"]}],
            "video": {"duration": 1800000},
        }
        assert VideoParser._detect_video_type(detail) == "image_set"


# ==================== 辅助方法测试：参数构造与发布时间 ====================


class TestBuildDetailParams:
    """_build_detail_params 参数构造测试。"""

    def test_build_params_contains_aweme_id(self) -> None:
        """参数含业务传入的 aweme_id。"""
        params = VideoParser._build_detail_params("123456")
        assert params["aweme_id"] == "123456"

    def test_build_params_contains_common_fixed(self) -> None:
        """参数含所有 COMMON_FIXED_PARAMS 字段。"""
        from crawlers.api_spec import COMMON_FIXED_PARAMS

        params = VideoParser._build_detail_params("123456")
        for key, value in COMMON_FIXED_PARAMS.items():
            assert params[key] == value


class TestFormatPublishTime:
    """_format_publish_time 发布时间格式化测试。"""

    def test_format_publish_time_normal(self) -> None:
        """Unix 秒正常转 ISO8601。"""
        # 1700000000 = 2023-11-14T22:13:20Z
        assert VideoParser._format_publish_time(1700000000) == "2023-11-14T22:13:20Z"

    def test_format_publish_time_none(self) -> None:
        """None → None。"""
        assert VideoParser._format_publish_time(None) is None

    def test_format_publish_time_zero(self) -> None:
        """0 → None。"""
        assert VideoParser._format_publish_time(0) is None

    def test_format_publish_time_negative(self) -> None:
        """负值 → None。"""
        assert VideoParser._format_publish_time(-1) is None


# ==================== 统计字段提取测试 ====================


class TestExtractStatistics:
    """_extract_statistics 统计字段提取测试。"""

    def test_statistics_normal(self) -> None:
        """正常 dict 提取 4 个字段。"""
        detail = {
            "statistics": {
                "digg_count": 10,
                "comment_count": 5,
                "share_count": 2,
                "collect_count": 1,
            }
        }
        assert VideoParser._extract_statistics(detail) == (10, 5, 2, 1)

    def test_statistics_missing(self) -> None:
        """statistics 缺失 → 全 0。"""
        assert VideoParser._extract_statistics({}) == (0, 0, 0, 0)

    def test_statistics_partial_fields(self) -> None:
        """部分字段缺失 → 缺失项为 0。"""
        detail = {"statistics": {"digg_count": 10}}
        assert VideoParser._extract_statistics(detail) == (10, 0, 0, 0)

    def test_statistics_string_int(self) -> None:
        """字符串数字自动转 int。"""
        detail = {"statistics": {"digg_count": "100", "comment_count": "50"}}
        assert VideoParser._extract_statistics(detail) == (100, 50, 0, 0)

    def test_statistics_invalid_type(self) -> None:
        """非 int/str 类型 → 0。"""
        detail = {"statistics": {"digg_count": [1, 2], "comment_count": {"a": 1}}}
        assert VideoParser._extract_statistics(detail) == (0, 0, 0, 0)
