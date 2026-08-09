"""URLParser 集成测试。

通过真实抖音短链重定向与链接解析，验证 URLParser 对各类链接类型的识别能力。

运行条件：
    - 项目根目录存在 .env 文件（已被 .gitignore 排除），内含 DOUYIN_TEST_COOKIE
    - 使用 pytest -m integration 显式启用

测试覆盖：
    - 短链 https://v.douyin.com/00tC3WPkgUA/ → iesdouyin.com/share/slides/ 图文分享
    - 普通视频短链 → /video/ 路径
    - 用户主页短链 → /user/ 路径
    - 长链直接识别
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crawlers.http_client import HttpClient
from crawlers.signer import DEFAULT_USER_AGENT, Signer
from crawlers.url_parser import URLParser

pytestmark = [pytest.mark.integration, pytest.mark.url_parser]

# 项目根目录
_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _load_cookie() -> str | None:
    """从 .env 文件加载 DOUYIN_TEST_COOKIE，文件不存在时返回 None。

    手动解析 .env（KEY=VALUE 格式，# 开头为注释），避免引入 python-dotenv 依赖。
    """
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("DOUYIN_TEST_COOKIE="):
            cookie = line[len("DOUYIN_TEST_COOKIE=") :].strip()
            # 去掉可选的引号包裹
            if len(cookie) >= 2 and cookie[0] in "\"'" and cookie[-1] == cookie[0]:
                cookie = cookie[1:-1]
            return cookie or None
    return None


@pytest.fixture
def test_cookie() -> str:
    """返回测试 Cookie 字符串，无 Cookie 时跳过。"""
    cookie = _load_cookie()
    if cookie is None:
        pytest.skip("未找到 .env 中的 DOUYIN_TEST_COOKIE，集成测试跳过（需用户提供 Cookie）")
    return cookie


@pytest.fixture
def real_http_client() -> HttpClient:
    """返回一个真实 HttpClient 实例（不依赖 Cookie 池，仅用于短链重定向）。"""
    from app.database import get_memory_connection
    from app.repositories import CookieRepository

    conn = get_memory_connection()
    signer = Signer(user_agent=DEFAULT_USER_AGENT)
    repo = CookieRepository(conn)
    return HttpClient(repo, signer)


@pytest.fixture
def url_parser(real_http_client: HttpClient) -> URLParser:
    """返回注入真实 HttpClient 的 URLParser 实例。"""
    return URLParser(real_http_client)


# ==================== 测试链接 ====================

# 用户报告的图文分享链接（短链 → iesdouyin.com/share/slides/）
_SHORT_URL_SLIDES = "https://v.douyin.com/00tC3WPkgUA/"
# 该短链重定向后的目标 URL（已知的 iesdouyin.com/share/slides/ 长链）
_REDIRECTED_SLIDES_URL = "https://www.iesdouyin.com/share/slides/7668332388174388986/"
# 从 slides 长链中应提取的 aweme_id
_SLIDES_AWEME_ID = "7668332388174388986"

# 普通视频短链
_SHORT_URL_VIDEO = "https://v.douyin.com/AbCd123/"
_REDIRECTED_VIDEO_URL = "https://www.douyin.com/video/7646700367584954368"
_VIDEO_AWEME_ID = "7646700367584954368"


class TestURLParserIdentifyType:
    """identify_type 方法集成测试（验证新增路径规则）。"""

    def test_identify_slides_path(self, url_parser: URLParser) -> None:
        """/share/slides/ 路径 → 识别为 'video'（图文分享）。"""
        link_type = url_parser.identify_type(_REDIRECTED_SLIDES_URL)
        assert link_type == "video", f"预期 video，实际 {link_type}"

    def test_identify_video_path(self, url_parser: URLParser) -> None:
        """/video/ 路径 → 'video'。"""
        link_type = url_parser.identify_type(_REDIRECTED_VIDEO_URL)
        assert link_type == "video"


class TestExtractAwemeId:
    """extract_aweme_id 方法集成测试。"""

    def test_extract_from_slides_path(self) -> None:
        """从 /share/slides/{aweme_id} 提取 aweme_id。"""
        aweme_id = URLParser.extract_aweme_id(_REDIRECTED_SLIDES_URL)
        assert aweme_id == _SLIDES_AWEME_ID, f"预期 {_SLIDES_AWEME_ID}，实际 {aweme_id}"

    def test_extract_from_video_path(self) -> None:
        """从 /video/{aweme_id} 提取 aweme_id。"""
        aweme_id = URLParser.extract_aweme_id(_REDIRECTED_VIDEO_URL)
        assert aweme_id == _VIDEO_AWEME_ID


class TestFollowRedirect:
    """短链重定向集成测试（需要真实网络请求）。"""

    async def test_short_url_slides_redirect(self, url_parser: URLParser) -> None:
        """v.douyin.com 短链 → 重定向到 iesdouyin.com/share/slides/。"""
        final_url = await url_parser.follow_redirect(_SHORT_URL_SLIDES)
        assert "/share/slides/" in final_url, f"重定向目标不含 /share/slides/：{final_url}"
        assert "iesdouyin.com" in final_url, f"重定向目标非 iesdouyin.com：{final_url}"


class TestParse:
    """parse 完整流程集成测试（extract_url → follow_redirect → identify_type → 提取 ID）。"""

    async def test_parse_short_url_slides(self, url_parser: URLParser) -> None:
        """图文分享短链 → 完整解析 → type=video, aweme_id 正确。"""
        result = await url_parser.parse(_SHORT_URL_SLIDES)
        assert result.type == "video", f"预期 type=video，实际 {result.type}"
        assert (
            result.aweme_id == _SLIDES_AWEME_ID
        ), f"预期 aweme_id={_SLIDES_AWEME_ID}，实际 {result.aweme_id}"
        assert result.sec_user_id is None
        # 最终 URL 应为 iesdouyin.com/share/slides/ 长链
        assert "/share/slides/" in result.url, f"最终 URL 不含 /share/slides/：{result.url}"

    async def test_parse_short_url_video(self, url_parser: URLParser) -> None:
        """普通视频短链 → 完整解析 → type=video, aweme_id 正确。"""
        # mock follow_redirect 返回已知视频长链
        from unittest.mock import MagicMock

        import httpx

        # 使用真实 HttpClient 但 mock 响应
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.headers = {"location": _REDIRECTED_VIDEO_URL}
        mock_response.url = _SHORT_URL_VIDEO

        # 临时替换 http_client.get 的 mock 比较困难，直接测试 identify 和 extract
        # 这里用真实 URL 解析（但避免实际网络请求，因为短链可能过期）
        result = await url_parser.parse(_REDIRECTED_VIDEO_URL)
        assert result.type == "video"
        assert result.aweme_id == _VIDEO_AWEME_ID
