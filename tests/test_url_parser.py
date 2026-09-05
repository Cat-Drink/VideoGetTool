"""URLParser 链接解析器单元测试。

覆盖 extract_url / identify_type / follow_redirect / parse 方法。
follow_redirect 与 parse 通过 mock HttpClient 测试，不打真实网络。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crawlers.exceptions import InvalidURLFormatError, NetworkError
from crawlers.url_parser import ParsedURL, URLParser


@pytest.fixture
def mock_http_client() -> MagicMock:
    """返回 mock HttpClient，get 方法为 AsyncMock 供 await 调用。"""
    client = MagicMock(name="HttpClient")
    client.get = AsyncMock(name="HttpClient.get")
    return client


@pytest.fixture
def url_parser(mock_http_client: MagicMock) -> URLParser:
    """返回注入 mock HttpClient 的 URLParser 实例。"""
    return URLParser(mock_http_client)


# ==================== extract_url 测试 ====================


class TestExtractUrl:
    """extract_url 方法测试。"""

    def test_extract_url_pure_short_link(self, url_parser: URLParser) -> None:
        """纯短链 ``https://v.douyin.com/xxxxx/`` 提取成功。"""
        text = "https://v.douyin.com/AbCdEf123/"
        assert url_parser.extract_url(text) == "https://v.douyin.com/AbCdEf123/"

    def test_extract_url_long_video_link(self, url_parser: URLParser) -> None:
        """纯长链 ``https://www.douyin.com/video/{aweme_id}`` 提取成功。"""
        text = "https://www.douyin.com/video/7646700367584954368"
        assert url_parser.extract_url(text) == "https://www.douyin.com/video/7646700367584954368"

    def test_extract_url_user_home_link(self, url_parser: URLParser) -> None:
        """主页链接 ``https://www.douyin.com/user/{sec_user_id}`` 提取成功。"""
        text = "https://www.douyin.com/user/MS4wLjABAAAAabc123"
        assert url_parser.extract_url(text) == "https://www.douyin.com/user/MS4wLjABAAAAabc123"

    def test_extract_url_share_command_video(self, url_parser: URLParser) -> None:
        """视频分享口令（含中文描述 + 短链）→ 提取短链。"""
        text = (
            "7.99 复制打开抖音，看看【守望先锋的图文】"
            " https://v.douyin.com/AbCdEf123/ 关注我，带你了解更多！"
        )
        assert url_parser.extract_url(text) == "https://v.douyin.com/AbCdEf123/"

    def test_extract_url_share_command_image_set(self, url_parser: URLParser) -> None:
        """图文分享口令（含中文描述 + 短链）→ 提取短链。"""
        text = (
            "2.34 复制打开抖音，看看【摄影者的图文作品】"
            " https://v.douyin.com/XyZ987/ : 此图文很精彩"
        )
        assert url_parser.extract_url(text) == "https://v.douyin.com/XyZ987/"

    def test_extract_url_multi_links_returns_first(self, url_parser: URLParser) -> None:
        """多链接文本 → 返回第一个抖音链接。"""
        text = "第一 https://v.douyin.com/Aaa111/ 第二 https://www.douyin.com/video/123"
        assert url_parser.extract_url(text) == "https://v.douyin.com/Aaa111/"

    def test_extract_url_no_link_returns_none(self, url_parser: URLParser) -> None:
        """无链接文本 → 返回 None。"""
        text = "这段文字完全没有链接，只是一段普通描述。"
        assert url_parser.extract_url(text) is None

    def test_extract_url_empty_string_returns_none(self, url_parser: URLParser) -> None:
        """空字符串 → 返回 None。"""
        assert url_parser.extract_url("") is None

    def test_extract_url_non_douyin_link_returns_none(self, url_parser: URLParser) -> None:
        """非抖音域名链接 → 返回 None。"""
        text = "https://www.example.com/video/123"
        assert url_parser.extract_url(text) is None

    def test_extract_url_chinese_punctuation(self, url_parser: URLParser) -> None:
        """含中文逗号/句号分隔的文本，URL 不被吞入描述部分。"""
        text = "看看这个视频，https://v.douyin.com/AbCd123/，很精彩。"
        assert url_parser.extract_url(text) == "https://v.douyin.com/AbCd123/"

    def test_extract_url_with_query_params(self, url_parser: URLParser) -> None:
        """带查询参数的长链完整提取。"""
        text = "https://www.douyin.com/video/7646700367584954368?previous_page=app_code_link"
        assert (
            url_parser.extract_url(text)
            == "https://www.douyin.com/video/7646700367584954368?previous_page=app_code_link"
        )

    def test_extract_url_trailing_punctuation_stripped(self, url_parser: URLParser) -> None:
        """URL 末尾粘连的英文句号/右括号被剥离。"""
        text = "(see https://v.douyin.com/AbCd123/)."
        assert url_parser.extract_url(text) == "https://v.douyin.com/AbCd123/"

    def test_extract_url_http_uppercase(self, url_parser: URLParser) -> None:
        """HTTP 大写也识别。"""
        text = "HTTPS://v.douyin.com/AbCd123/"
        assert url_parser.extract_url(text) == "HTTPS://v.douyin.com/AbCd123/"

    def test_extract_url_short_link_without_trailing_slash(self, url_parser: URLParser) -> None:
        """短链末尾无 / 也识别。"""
        text = "https://v.douyin.com/AbCd123"
        assert url_parser.extract_url(text) == "https://v.douyin.com/AbCd123"

    def test_extract_url_iesdouyin_domain(self, url_parser: URLParser) -> None:
        """iesdouyin.com 旧域名也识别。"""
        text = "https://www.iesdouyin.com/share/video/7646700367584954368"
        assert (
            url_parser.extract_url(text)
            == "https://www.iesdouyin.com/share/video/7646700367584954368"
        )


# ==================== extract_short_urls 测试（v0.1.5） ====================


class TestExtractShortUrls:
    """extract_short_urls 方法测试（v0.1.5：分享文本短链批量提取）。"""

    def test_extract_short_urls_from_share_text(self, url_parser: URLParser) -> None:
        """用户反馈 #1 示例：完整分享文本提取短链。"""
        text = (
            "7.99 OXM:/ z@T.yG :8pm 06/15 怎么远程操控另一台手机 "
            "# 二次元 # 手机 # 电脑知识 # 玩转数码 # 软件  "
            "https://v.douyin.com/RNUDiCoVdd4/ 复制此链接，打开Dou音搜索，直接观看视频！"
        )
        result = url_parser.extract_short_urls(text)
        assert result == ["https://v.douyin.com/RNUDiCoVdd4/"]

    def test_extract_short_urls_pure_link(self, url_parser: URLParser) -> None:
        """纯短链输入 → 返回单元素列表。"""
        text = "https://v.douyin.com/AbCd123/"
        assert url_parser.extract_short_urls(text) == ["https://v.douyin.com/AbCd123/"]

    def test_extract_short_urls_multiple_in_one_line(self, url_parser: URLParser) -> None:
        """单行含多个短链 → 全部提取，保持顺序。"""
        text = "第一 https://v.douyin.com/Aaa111/ 第二 https://v.douyin.com/Bbb222/"
        assert url_parser.extract_short_urls(text) == [
            "https://v.douyin.com/Aaa111/",
            "https://v.douyin.com/Bbb222/",
        ]

    def test_extract_short_urls_multi_line(self, url_parser: URLParser) -> None:
        """多行文本 → 提取所有行的短链。"""
        text = "https://v.douyin.com/Aaa111/\n描述行无链接\nhttps://v.douyin.com/Bbb222/\n"
        assert url_parser.extract_short_urls(text) == [
            "https://v.douyin.com/Aaa111/",
            "https://v.douyin.com/Bbb222/",
        ]

    def test_extract_short_urls_no_link_returns_empty(self, url_parser: URLParser) -> None:
        """纯描述文字无短链 → 返回空列表。"""
        text = "这段文字完全没有链接，只是一段普通描述。"
        assert url_parser.extract_short_urls(text) == []

    def test_extract_short_urls_empty_string(self, url_parser: URLParser) -> None:
        """空字符串 → 返回空列表。"""
        assert url_parser.extract_short_urls("") == []

    def test_extract_short_urls_long_link_not_matched(self, url_parser: URLParser) -> None:
        """长链（www.douyin.com/video/xxx）不被匹配（仅匹配 v.douyin.com 短链）。"""
        text = "https://www.douyin.com/video/7646700367584954368"
        assert url_parser.extract_short_urls(text) == []

    def test_extract_short_urls_without_trailing_slash(self, url_parser: URLParser) -> None:
        """短链末尾无 / 也识别。"""
        text = "https://v.douyin.com/AbCd123"
        assert url_parser.extract_short_urls(text) == ["https://v.douyin.com/AbCd123"]

    def test_extract_short_urls_uppercase_domain(self, url_parser: URLParser) -> None:
        """大写 V.DOUYIN.COM 也识别。"""
        text = "HTTPS://V.DOUYIN.COM/AbCd123/"
        assert url_parser.extract_short_urls(text) == ["HTTPS://V.DOUYIN.COM/AbCd123/"]

    def test_extract_short_urls_preserves_order(self, url_parser: URLParser) -> None:
        """多个短链按出现顺序返回。"""
        text = (
            "https://v.douyin.com/ZZZ999/ https://v.douyin.com/Aaa111/ https://v.douyin.com/Mmm555/"
        )
        result = url_parser.extract_short_urls(text)
        assert result == [
            "https://v.douyin.com/ZZZ999/",
            "https://v.douyin.com/Aaa111/",
            "https://v.douyin.com/Mmm555/",
        ]


class TestParsedURLDataclass:
    """ParsedURL dataclass 不可变性与字段测试。"""

    def test_parsed_url_is_frozen(self) -> None:
        """ParsedURL 是 frozen dataclass，不可修改。"""
        parsed = ParsedURL(
            type="video",
            url="https://www.douyin.com/video/123",
            aweme_id="123",
            sec_user_id=None,
            original_text="原始文本",
        )
        with pytest.raises(AttributeError):
            parsed.type = "user_home"  # type: ignore[misc]

    def test_parsed_url_fields(self) -> None:
        """ParsedURL 字段正确赋值。"""
        parsed = ParsedURL(
            type="user_home",
            url="https://www.douyin.com/user/MS4w",
            aweme_id=None,
            sec_user_id="MS4w",
            original_text="原始文本",
        )
        assert parsed.type == "user_home"
        assert parsed.aweme_id is None
        assert parsed.sec_user_id == "MS4w"
        assert parsed.original_text == "原始文本"


# ==================== identify_type 测试 ====================


class TestIdentifyType:
    """identify_type 方法测试。"""

    def test_identify_type_video_path(self, url_parser: URLParser) -> None:
        """路径含 /video/ → 'video'。"""
        assert (
            url_parser.identify_type("https://www.douyin.com/video/7646700367584954368") == "video"
        )

    def test_identify_type_video_query_param(self, url_parser: URLParser) -> None:
        """查询参数含 aweme_id → 'video'。"""
        url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=123"
        assert url_parser.identify_type(url) == "video"

    def test_identify_type_user_home_path(self, url_parser: URLParser) -> None:
        """路径含 /user/ → 'user_home'。"""
        url = "https://www.douyin.com/user/MS4wLjABAAAAabc123"
        assert url_parser.identify_type(url) == "user_home"

    def test_identify_type_user_home_query_param(self, url_parser: URLParser) -> None:
        """查询参数含 sec_user_id → 'user_home'。"""
        url = "https://www.douyin.com/aweme/v1/web/user/profile/other/?sec_user_id=MS4w"
        assert url_parser.identify_type(url) == "user_home"

    def test_identify_type_user_home_priority_over_video(self, url_parser: URLParser) -> None:
        """同时含 /user/ 和 /video/ 时，user_home 优先。"""
        # 实际不会出现，但验证优先级规则
        url = "https://www.douyin.com/user/MS4w/video/123"
        assert url_parser.identify_type(url) == "user_home"

    def test_identify_type_share_video_path(self, url_parser: URLParser) -> None:
        """iesdouyin 分享链接 /share/video/{id} → 'video'。"""
        url = "https://www.iesdouyin.com/share/video/7646700367584954368"
        assert url_parser.identify_type(url) == "video"

    def test_identify_type_invalid_raises(self, url_parser: URLParser) -> None:
        """无法识别的路径 → 抛 InvalidURLFormatError。"""
        url = "https://www.douyin.com/discover/123"
        with pytest.raises(InvalidURLFormatError):
            url_parser.identify_type(url)

    def test_identify_type_empty_path_raises(self, url_parser: URLParser) -> None:
        """根路径无任何标识 → 抛 InvalidURLFormatError。"""
        url = "https://www.douyin.com/"
        with pytest.raises(InvalidURLFormatError):
            url_parser.identify_type(url)

    def test_identify_type_invalid_url_raises(self, url_parser: URLParser) -> None:
        """URL 格式无效 → 抛 InvalidURLFormatError。"""
        with pytest.raises(InvalidURLFormatError):
            url_parser.identify_type("not_a_url")


# ==================== extract_aweme_id / extract_sec_user_id 测试 ====================


class TestExtractIds:
    """extract_aweme_id / extract_sec_user_id 方法测试。"""

    def test_extract_aweme_id_from_path(self) -> None:
        """从路径 /video/{id} 提取 aweme_id。"""
        url = "https://www.douyin.com/video/7646700367584954368"
        assert URLParser.extract_aweme_id(url) == "7646700367584954368"

    def test_extract_aweme_id_from_share_path(self) -> None:
        """从分享路径 /share/video/{id} 提取 aweme_id。"""
        url = "https://www.iesdouyin.com/share/video/7646700367584954368"
        assert URLParser.extract_aweme_id(url) == "7646700367584954368"

    def test_extract_aweme_id_from_query(self) -> None:
        """从查询参数 ?aweme_id=xxx 提取 aweme_id。"""
        url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=123"
        assert URLParser.extract_aweme_id(url) == "123"

    def test_extract_aweme_id_not_found(self) -> None:
        """无 aweme_id → 返回 None。"""
        url = "https://www.douyin.com/user/MS4w"
        assert URLParser.extract_aweme_id(url) is None

    def test_extract_sec_user_id_from_path(self) -> None:
        """从路径 /user/{sec_uid} 提取 sec_user_id。"""
        url = "https://www.douyin.com/user/MS4wLjABAAAAabc123"
        assert URLParser.extract_sec_user_id(url) == "MS4wLjABAAAAabc123"

    def test_extract_sec_user_id_from_query(self) -> None:
        """从查询参数 ?sec_user_id=xxx 提取 sec_user_id。"""
        url = "https://www.douyin.com/aweme/v1/web/user/profile/other/?sec_user_id=MS4w"
        assert URLParser.extract_sec_user_id(url) == "MS4w"

    def test_extract_sec_user_id_not_found(self) -> None:
        """无 sec_user_id → 返回 None。"""
        url = "https://www.douyin.com/video/123"
        assert URLParser.extract_sec_user_id(url) is None


# ==================== follow_redirect 测试 ====================


class TestFollowRedirect:
    """follow_redirect 方法测试（mock HttpClient.get）。"""

    async def test_follow_redirect_with_location_header(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """响应含 Location 头（抖音域名）→ 返回校验通过的 Location 值。"""
        mock_response = MagicMock(name="Response")
        mock_response.headers = {"location": "https://www.douyin.com/video/123"}
        mock_response.url = "https://v.douyin.com/AbCd123/"
        mock_http_client.get.return_value = mock_response

        result = await url_parser.follow_redirect("https://v.douyin.com/AbCd123/")

        assert result == "https://www.douyin.com/video/123"
        mock_http_client.get.assert_awaited_once_with(
            "https://v.douyin.com/AbCd123/",
            use_cookie_pool=False,
        )

    async def test_follow_redirect_without_location_header(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """响应无 Location 头 → 返回 response.url 字符串。"""
        mock_response = MagicMock(name="Response")
        mock_response.headers = {}
        mock_response.url = "https://www.douyin.com/video/123"
        mock_http_client.get.return_value = mock_response

        result = await url_parser.follow_redirect("https://v.douyin.com/AbCd123/")

        assert result == "https://www.douyin.com/video/123"

    async def test_follow_redirect_empty_location_header(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """Location 头为空字符串 → 回退到 response.url。"""
        mock_response = MagicMock(name="Response")
        # headers.get("location") 返回 ""（falsy）→ 走 response.url 分支
        mock_response.headers = {"location": ""}
        mock_response.url = "https://www.douyin.com/video/456"
        mock_http_client.get.return_value = mock_response

        result = await url_parser.follow_redirect("https://v.douyin.com/AbCd123/")

        assert result == "https://www.douyin.com/video/456"

    async def test_follow_redirect_calls_get_without_cookie_pool(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """follow_redirect 调用 HttpClient.get 时 use_cookie_pool=False（短链不需 Cookie）。"""
        mock_response = MagicMock(name="Response")
        mock_response.headers = {"location": "https://www.douyin.com/video/789"}
        mock_response.url = "https://v.douyin.com/x/"
        mock_http_client.get.return_value = mock_response

        await url_parser.follow_redirect("https://v.douyin.com/x/")

        # 断言 use_cookie_pool=False 被传入
        call_args = mock_http_client.get.call_args
        assert call_args.kwargs.get("use_cookie_pool") is False

    async def test_follow_redirect_network_error_propagates(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """HttpClient.get 抛 NetworkError → 异常透传给调用方。"""
        mock_http_client.get.side_effect = NetworkError("连接超时")

        with pytest.raises(NetworkError, match="连接超时"):
            await url_parser.follow_redirect("https://v.douyin.com/AbCd123/")


# ==================== parse 测试 ====================


class TestParse:
    """parse 方法测试（编排 extract_url → follow_redirect → identify_type → 构造 ParsedURL）。"""

    async def test_parse_long_video_link(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """长链视频 → 直接识别，不调用 follow_redirect，aweme_id 提取成功。"""
        text = "https://www.douyin.com/video/7646700367584954368"

        result = await url_parser.parse(text)

        assert result.type == "video"
        assert result.url == "https://www.douyin.com/video/7646700367584954368"
        assert result.aweme_id == "7646700367584954368"
        assert result.sec_user_id is None
        assert result.original_text == text
        # 长链不应触发 follow_redirect（即 HttpClient.get 不应被调用）
        mock_http_client.get.assert_not_awaited()

    async def test_parse_long_user_home_link(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """长链主页 → 直接识别，sec_user_id 提取成功。"""
        text = "https://www.douyin.com/user/MS4wLjABAAAAabc123"

        result = await url_parser.parse(text)

        assert result.type == "user_home"
        assert result.url == "https://www.douyin.com/user/MS4wLjABAAAAabc123"
        assert result.aweme_id is None
        assert result.sec_user_id == "MS4wLjABAAAAabc123"
        assert result.original_text == text
        mock_http_client.get.assert_not_awaited()

    async def test_parse_short_link_video(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """短链视频 → follow_redirect 返回抖音域名 Location，aweme_id 提取成功。"""
        text = "https://v.douyin.com/AbCd123/"
        mock_response = MagicMock(name="Response")
        mock_response.headers = {"location": "https://www.douyin.com/video/9999"}
        mock_response.url = "https://v.douyin.com/AbCd123/"
        mock_http_client.get.return_value = mock_response

        result = await url_parser.parse(text)

        assert result.type == "video"
        assert result.url == "https://www.douyin.com/video/9999"
        assert result.aweme_id == "9999"
        assert result.sec_user_id is None
        assert result.original_text == text
        mock_http_client.get.assert_awaited_once()

    async def test_parse_short_link_user_home(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """短链主页 → follow_redirect 返回抖音域名 Location，sec_user_id 提取成功。"""
        text = "https://v.douyin.com/AbCd456/"
        mock_response = MagicMock(name="Response")
        mock_response.headers = {"location": "https://www.douyin.com/user/MS4wLjABAAAAxyz"}
        mock_response.url = "https://v.douyin.com/AbCd456/"
        mock_http_client.get.return_value = mock_response

        result = await url_parser.parse(text)

        assert result.type == "user_home"
        assert result.url == "https://www.douyin.com/user/MS4wLjABAAAAxyz"
        assert result.aweme_id is None
        assert result.sec_user_id == "MS4wLjABAAAAxyz"

    async def test_parse_share_command_with_short_link(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """分享口令（含中文描述 + 短链）→ 提取短链 → follow_redirect → ParsedURL。"""
        text = (
            "7.99 复制打开抖音，看看【守望先锋的图文】"
            " https://v.douyin.com/AbCdEf123/ 关注我，带你了解更多！"
        )
        mock_response = MagicMock(name="Response")
        mock_response.headers = {"location": "https://www.douyin.com/video/7646700367584954368"}
        mock_response.url = "https://v.douyin.com/AbCdEf123/"
        mock_http_client.get.return_value = mock_response

        result = await url_parser.parse(text)

        assert result.type == "video"
        assert result.aweme_id == "7646700367584954368"
        # original_text 保留原始分享口令全文
        assert result.original_text == text

    async def test_parse_long_video_link_with_query_params(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """长链带查询参数 → 完整保留，aweme_id 从路径提取。"""
        text = "https://www.douyin.com/video/7646700367584954368?previous_page=app_code_link"

        result = await url_parser.parse(text)

        assert result.type == "video"
        assert result.aweme_id == "7646700367584954368"
        assert (
            result.url
            == "https://www.douyin.com/video/7646700367584954368?previous_page=app_code_link"
        )

    async def test_parse_no_link_raises_invalid_url_format(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """文本中无抖音链接 → 抛 InvalidURLFormatError。"""
        text = "这段文字完全没有链接，只是一段普通描述。"

        with pytest.raises(InvalidURLFormatError, match="未找到抖音链接"):
            await url_parser.parse(text)

        # 无链接时不应调用 HttpClient
        mock_http_client.get.assert_not_awaited()

    async def test_parse_empty_text_raises(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """空文本 → 抛 InvalidURLFormatError。"""
        with pytest.raises(InvalidURLFormatError):
            await url_parser.parse("")

    async def test_parse_non_douyin_link_raises(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """文本含非抖音链接 → extract_url 返回 None → 抛 InvalidURLFormatError。"""
        text = "https://www.example.com/video/123"

        with pytest.raises(InvalidURLFormatError):
            await url_parser.parse(text)

    async def test_parse_short_link_network_error_propagates(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """短链 follow_redirect 网络异常 → 异常透传。"""
        text = "https://v.douyin.com/AbCd123/"
        mock_http_client.get.side_effect = NetworkError("DNS 解析失败")

        with pytest.raises(NetworkError, match="DNS 解析失败"):
            await url_parser.parse(text)

    async def test_parse_preserves_original_text(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """parse 保留 original_text 字段（含中文描述与多余空白）。"""
        text = "  前后有空格  https://www.douyin.com/video/111  "

        result = await url_parser.parse(text)

        assert result.original_text == text

    async def test_parse_short_link_uppercase_domain(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """短链域名大写 V.DOUYIN.COM 仍触发 follow_redirect。"""
        text = "HTTPS://V.DOUYIN.COM/AbCd123/"
        mock_response = MagicMock(name="Response")
        mock_response.headers = {"location": "https://www.douyin.com/video/222"}
        mock_response.url = "HTTPS://V.DOUYIN.COM/AbCd123/"
        mock_http_client.get.return_value = mock_response

        result = await url_parser.parse(text)

        assert result.type == "video"
        assert result.aweme_id == "222"
        mock_http_client.get.assert_awaited_once()


# ==================== 短链重定向安全（审计 M9） ====================


class TestFollowRedirectSecurity:
    """短链落地域名校验与重定向限制测试（审计 M9）。"""

    async def test_redirect_to_non_douyin_rejected(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """Location 指向非抖音域名（如内网/元数据地址）→ 拒绝。"""
        mock_302 = MagicMock(name="Response302")
        mock_302.status_code = 302
        mock_302.headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        mock_http_client.get.return_value = mock_302

        with pytest.raises(InvalidURLFormatError, match="非抖音域名"):
            await url_parser.follow_redirect("https://v.douyin.com/AbCd123/")
        # 只发起了一跳请求，未对非法主机发出后续请求
        assert mock_http_client.get.await_count == 1

    async def test_redirect_userinfo_bypass_rejected(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """Location 用 userinfo@ 伪装抖音域名 → 拒绝（urlparse hostname 免疫）。"""
        mock_302 = MagicMock(name="Response302")
        mock_302.status_code = 302
        mock_302.headers = {"location": "https://v.douyin.com:443@evil.com/video/1"}
        mock_http_client.get.return_value = mock_302

        with pytest.raises(InvalidURLFormatError):
            await url_parser.follow_redirect("https://v.douyin.com/AbCd123/")

    async def test_relative_location_resolved(
        self,
        url_parser: URLParser,
        mock_http_client: MagicMock,
    ) -> None:
        """相对 Location（/video/1）→ urljoin 解析后校验。"""
        mock_response = MagicMock(name="Response")
        mock_response.headers = {"location": "/video/123"}
        mock_response.url = "https://v.douyin.com/AbCd123/"
        mock_http_client.get.return_value = mock_response

        result = await url_parser.follow_redirect("https://v.douyin.com/AbCd123/")
        # urljoin(short_url, "/video/123") → https://v.douyin.com/video/123
        assert result == "https://v.douyin.com/video/123"


class TestIsDouyinUrl:
    """_is_douyin_url 域名判定（审计 M9：urlparse 提取 host）。"""

    def test_userinfo_bypass_rejected(self):
        """userinfo@ 语法伪装 → host 识别为 evil.com → 拒绝。"""
        assert not URLParser._is_douyin_url("https://v.douyin.com:443@evil.com/x")
        assert not URLParser._is_douyin_url("https://v.douyin.com.evil.com/x")
        assert not URLParser._is_douyin_url("https://evil.com/v.douyin.com/video/1")

    def test_trailing_dot_normalized(self):
        """尾点（FQDN 形式 v.douyin.com.）→ 规范化后放行。"""
        assert URLParser._is_douyin_url("https://v.douyin.com./x")
        assert URLParser._is_douyin_url("https://V.DOUYIN.COM./x")

    def test_valid_domains_accepted(self):
        assert URLParser._is_douyin_url("https://v.douyin.com/abc")
        assert URLParser._is_douyin_url("https://www.douyin.com/video/1")
        assert URLParser._is_douyin_url("https://iesdouyin.com/share/slides/1")

    def test_invalid_scheme_rejected(self):
        assert not URLParser._is_douyin_url("ftp://v.douyin.com/x")
        assert not URLParser._is_douyin_url("not-a-url")

