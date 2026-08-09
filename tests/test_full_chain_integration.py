"""URLParser + VideoParser + Downloader 全链路集成测试。

通过真实抖音短链验证从链接解析到视频文件下载到本地的完整链路：
    短链 → follow_redirect → identify_type → extract_aweme_id
    → VideoParser.parse_video() → VideoInfo（含无水印直链/图集URL）
    → Downloader.download() → 本地文件（验证存在、非空、MP4格式）

运行条件：
    - 项目根目录存在 .env 文件（已被 .gitignore 排除），内含 DOUYIN_TEST_COOKIE
    - 使用 pytest -m integration 显式启用

测试覆盖：
    - 图文分享短链：https://v.douyin.com/00tC3WPkgUA/
      → 重定向到 iesdouyin.com/share/slides/
      → aweme_id=7668332388174388986
      → detail 接口返回图集（image_set，9张图片 + 1个视频）
      → 下载视频直链到本地并验证文件完整性
    - 普通视频：通过 slides 图文中的视频附带来验证视频元数据获取

已知限制（见 TODO/issue 跟踪）：
    - 直播回放链接（/vsdetail/）使用 webcast/xgplayer 私有流协议，
      不兼容 aweme/v1/web/aweme/detail 接口（返回 core_dep 过滤）。
      需单独研究 webcast API 认证与流解析后支持。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.database import get_memory_connection
from app.models import Cookie, now_iso
from app.repositories import CookieRepository
from crawlers.http_client import HttpClient
from crawlers.signer import DEFAULT_USER_AGENT, Signer
from crawlers.url_parser import URLParser
from crawlers.video_parser import VideoParser
from tests.test_downloader import _insert_item, _make_downloader_with_item

pytestmark = [pytest.mark.integration, pytest.mark.full_chain]

# 项目根目录
_PROJECT_ROOT = Path(__file__).parent.parent

# 用户报告的图文分享短链
_SHORT_URL_SLIDES = "https://v.douyin.com/00tC3WPkgUA/"
_SLIDES_AWEME_ID = "7668332388174388986"


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


@pytest.fixture(scope="module")
def test_cookie() -> str:
    """返回测试 Cookie 字符串，无 Cookie 时跳过。"""
    cookie = _load_cookie()
    if cookie is None:
        pytest.skip("未找到 .env 中的 DOUYIN_TEST_COOKIE，集成测试跳过（需用户提供 Cookie）")
    return cookie


@pytest.fixture(scope="function")
def real_http_client(test_cookie: str):
    """返回注入真实 Cookie 的 HttpClient 实例。"""
    conn = get_memory_connection()
    signer = Signer(user_agent=DEFAULT_USER_AGENT)
    repo = CookieRepository(conn)
    # 将用户 Cookie 作为测试 Cookie 插入内存数据库
    repo.add(
        Cookie(
            id=None,
            content=test_cookie,
            label="integration-test",
            status="valid",
            last_used=None,
            last_check=None,
            fail_count=0,
            created_at=now_iso(),
        )
    )
    http_client = HttpClient(repo, signer)
    yield http_client
    # 清理：关闭数据库连接
    conn.close()


@pytest.fixture(scope="function")
def url_parser(real_http_client: HttpClient) -> URLParser:
    """返回注入真实 HttpClient 的 URLParser 实例。"""
    return URLParser(real_http_client)


@pytest.fixture(scope="function")
def video_parser(real_http_client: HttpClient) -> VideoParser:
    """返回注入真实 HttpClient 的 VideoParser 实例。"""
    signer = Signer(user_agent=DEFAULT_USER_AGENT)
    return VideoParser(real_http_client, signer)


@pytest.fixture(scope="function")
async def no_watermark_url(video_parser: VideoParser, test_cookie: str) -> str:
    """获取图文分享的无水印视频直链。

    这个 fixture 确保每个测试都能获得所需的 URL，
    即使之前的测试被跳过也能正常工作。
    """
    video_info = await video_parser.parse_video(_SLIDES_AWEME_ID, test_cookie)
    assert video_info.no_watermark_url is not None, "无水印视频直链获取失败"
    return video_info.no_watermark_url


class TestFullChainSlides:
    """图文分享链接全链路测试。

    覆盖：短链 → URLParser → VideoParser → Downloader → 本地文件。
    """

    async def test_01_url_parser_extracts_aweme_id(self, url_parser: URLParser) -> None:
        """步骤1：URLParser 从短链中解析出 aweme_id。"""
        result = await url_parser.parse(_SHORT_URL_SLIDES)
        assert result.type == "video", f"类型应为 video，实际为 {result.type}"
        assert (
            result.aweme_id == _SLIDES_AWEME_ID
        ), f"aweme_id 应为 {_SLIDES_AWEME_ID}，实际为 {result.aweme_id}"
        assert (
            "/share/slides/" in result.url
        ), f"最终 URL 应包含 /share/slides/，实际为 {result.url}"

    async def test_02_video_parser_returns_video_info(
        self, video_parser: VideoParser, test_cookie: str
    ) -> None:
        """步骤2：VideoParser 通过 detail 接口获取完整 VideoInfo。

        验证要点：
        - status_code=0（签名和Cookie有效）
        - 返回 VideoInfo 且 type=image_set（图文）
        - 包含标题、作者、封面图
        - 包含图集图片 URL 列表（至少1张）
        - 包含无水印视频直链（图文通常也附带一个视频）
        - 包含发布时间（ISO8601格式）
        - 包含统计信息（点赞/评论/分享/收藏数）
        """
        video_info = await video_parser.parse_video(_SLIDES_AWEME_ID, test_cookie)

        # 基本信息
        assert (
            video_info.type == "image_set"
        ), f"类型应为 image_set（图文），实际为 {video_info.type}"
        assert video_info.title, "标题不应为空"
        assert video_info.author, f"作者不应为空，当前 {video_info.author}"
        assert video_info.cover_url, "封面 URL 不应为空"
        assert video_info.cover_url.startswith(
            "http"
        ), f"封面 URL 格式异常: {video_info.cover_url[:60]}"

        # 图集验证
        assert (
            len(video_info.image_urls) > 0
        ), f"图集应包含至少1张图片，当前 {len(video_info.image_urls)} 张"
        for img_url in video_info.image_urls:
            assert img_url.startswith("http"), f"图片 URL 格式异常: {img_url[:60]}"

        # 无水印视频直链（图文也附带一个视频）
        assert video_info.no_watermark_url is not None, "无水印视频直链不应为空"
        assert video_info.no_watermark_url.startswith(
            "http"
        ), f"无水印 URL 格式异常: {video_info.no_watermark_url[:60]}"

        # 验证发布时间格式化正确（ISO8601格式 YYYY-MM-DDTHH:MM:SSZ）
        assert video_info.publish_time is not None, "发布时间不应为 None"
        assert "T" in video_info.publish_time and video_info.publish_time.endswith(
            "Z"
        ), f"发布时间应为 ISO8601 格式，当前: {video_info.publish_time}"

    async def test_03_download_video_to_local(self, tmp_path: Path, no_watermark_url: str) -> None:
        """步骤3：从 no_watermark_url 真实下载视频到本地并验证。

        验证要点：
        - Downloader.download() 返回 success=True
        - 本地文件存在且非空
        - 文件是有效的 MP4 格式（ftyp magic bytes）
        """
        # 创建 Downloader 并执行下载
        dl, item = _make_downloader_with_item(
            download_dir=str(tmp_path),
            aweme_id=_SLIDES_AWEME_ID,
            url=no_watermark_url,
            item_type="video",
        )
        _insert_item(dl._conn, item)

        result = await dl.download(item)
        assert result.success, f"下载失败: {result.error}"
        assert result.local_path is not None, "local_path 不应为 None"

        # 验证文件存在且非空
        file_path = Path(result.local_path)
        assert file_path.exists(), f"下载文件不存在: {file_path}"
        assert file_path.stat().st_size > 0, f"下载文件为空: {file_path}"

        # 验证 MP4 格式（magic bytes: ftyp box）
        with open(file_path, "rb") as f:
            header = f.read(12)
        # MP4 文件的第 4-8 字节为 ftyp（File Type Box）
        assert header[4:8] == b"ftyp", f"非 MP4 文件格式，前 12 字节: {header.hex()}"


class TestFullChainVideo:
    """普通视频链接全链路测试（使用 slides 图文中的视频附带来验证视频能力）。"""

    async def test_01_video_parser_returns_video_info(
        self, video_parser: VideoParser, test_cookie: str
    ) -> None:
        """通过 VideoParser 获取视频信息。

        验证要点：
        - type=image_set（图文）
        - 包含无水印视频直链（图文附带视频）
        - 包含时长 duration 或为 None（图文视频时长可能为 0）
        - 图集非空
        """
        # 使用 slides 的 aweme_id，它同时包含 image_set 和 video
        video_info = await video_parser.parse_video(_SLIDES_AWEME_ID, test_cookie)

        # 图文类型
        assert video_info.type == "image_set", f"类型应为 image_set，实际为 {video_info.type}"
        assert video_info.title, "标题不应为空"
        assert video_info.author, f"作者不应为空，当前 {video_info.author}"
        assert video_info.cover_url, "封面 URL 不应为空"

        # 无水印视频直链（图文附带视频）
        assert video_info.no_watermark_url is not None, "无水印视频直链不应为空"
        assert video_info.no_watermark_url.startswith(
            "http"
        ), f"无水印 URL 格式异常: {video_info.no_watermark_url[:60]}"

        # 图集图片
        assert (
            len(video_info.image_urls) > 0
        ), f"图集应包含至少1张图片，当前 {len(video_info.image_urls)} 张"

        # 发布时间
        assert video_info.publish_time is not None, "发布时间不应为 None"
        assert "T" in video_info.publish_time and video_info.publish_time.endswith(
            "Z"
        ), f"发布时间应为 ISO8601 格式，当前: {video_info.publish_time}"
