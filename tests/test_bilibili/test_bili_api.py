"""B 站（Bilibili）API 路由集成测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.state import ctx
from crawlers.bilibili.bili_http_client import BiliAPIError
from crawlers.bilibili.bili_url_parser import BiliParsedURL


# === 测试用数据构造 ===


def _parsed_video(bvid: str = "BV1xx411c7mD") -> BiliParsedURL:
    """构造视频类型解析结果。"""
    return BiliParsedURL(
        type="video",
        url=f"https://www.bilibili.com/video/{bvid}",
        bvid=bvid,
        av_id=12345678,
        mid=None,
        page=1,
    )


def _parsed_user_home(mid: int = 12345) -> BiliParsedURL:
    """构造用户主页类型解析结果。"""
    return BiliParsedURL(
        type="user_home",
        url=f"https://space.bilibili.com/{mid}",
        bvid=None,
        av_id=None,
        mid=mid,
        page=1,
    )


def _video_info(bvid: str = "BV1xx411c7mD") -> MagicMock:
    """构造视频信息对象（模拟 BiliVideoParser.parse_video 返回值）。"""
    return MagicMock(
        bvid=bvid,
        aid=12345678,
        title="测试视频标题",
        author="测试UP主",
        author_mid=12345,
        cover_url="https://i0.hdslb.com/bfs/archive/cover.jpg",
        duration=300,
        description="这是一个测试视频描述",
        pages=[
            MagicMock(cid=111, page=1, title="P1", duration=120),
            MagicMock(cid=222, page=2, title="P2", duration=180),
        ],
        view_count=10000,
        danmaku_count=500,
        pubdate=1700000000,
        tags=["测试", "B站"],
    )


def _playurl_result(bvid: str = "BV1xx411c7mD") -> MagicMock:
    """构造播放流对象（模拟 BiliVideoParser.parse_playurl 返回值）。"""
    return MagicMock(
        bvid=bvid,
        cid=111,
        quality=80,
        quality_name="1080P",
        dash=True,
        video_streams=[
            MagicMock(id=1, url="https://upos-bilibili.com/video.mp4", mime_type="video/mp4", codecs="avc1.64001F", width=1920, height=1080),
        ],
        audio_streams=[
            MagicMock(id=2, url="https://upos-bilibili.com/audio.m4a", mime_type="audio/mp4", codecs="mp4a.40.2"),
        ],
        url="",
        duration=300,
    )


def _playurl_flv_result(bvid: str = "BV1xx411c7mD") -> MagicMock:
    """构造非 DASH 播放流（FLV 直链）。"""
    return MagicMock(
        bvid=bvid,
        cid=111,
        quality=80,
        quality_name="1080P",
        dash=False,
        video_streams=[],
        audio_streams=[],
        url="https://upos-bilibili.com/video.flv",
        duration=300,
    )


# === Fixture ===


@pytest.fixture
def api_client() -> TestClient:
    """创建只挂载 bilibili router 的 TestClient，并隔离全局上下文。"""
    from backend.api.bilibili import router

    ctx_fields = ("bili_url_parser", "bili_video_parser", "bili_http_client", "bili_signer", "bili_user_crawler")
    previous = {field: getattr(ctx, field) for field in ctx_fields}

    # 创建 Mock 组件
    bili_url_parser = MagicMock(name="BiliURLParser")
    bili_url_parser.parse = AsyncMock(name="BiliURLParser.parse")
    bili_video_parser = MagicMock(name="BiliVideoParser")
    bili_video_parser.parse_video = AsyncMock(name="BiliVideoParser.parse_video")
    bili_video_parser.parse_playurl = AsyncMock(name="BiliVideoParser.parse_playurl")
    bili_http_client = MagicMock(name="BiliHttpClient")
    bili_http_client.get_json = AsyncMock(name="BiliHttpClient.get_json")
    bili_http_client.set_cookie = MagicMock(name="BiliHttpClient.set_cookie")
    bili_http_client._client = MagicMock()
    bili_signer = MagicMock(name="BiliSigner")
    bili_signer.refresh_keys = AsyncMock(name="BiliSigner.refresh_keys")
    bili_user_crawler = MagicMock(name="BiliUserCrawler")
    bili_user_crawler.fetch_user_posts = MagicMock(name="BiliUserCrawler.fetch_user_posts")
    bili_user_crawler.fetch_user_posts_with_meta = AsyncMock(
        name="BiliUserCrawler.fetch_user_posts_with_meta",
        return_value=([], False, 0),
    )

    ctx.bili_url_parser = bili_url_parser
    ctx.bili_video_parser = bili_video_parser
    ctx.bili_http_client = bili_http_client
    ctx.bili_signer = bili_signer
    ctx.bili_user_crawler = bili_user_crawler

    app = FastAPI()
    app.include_router(router, prefix="/api/bilibili")
    client = TestClient(app)
    try:
        yield client
    finally:
        for field, value in previous.items():
            setattr(ctx, field, value)


def _async_gen(*items):
    """辅助函数：返回异步生成器，用于 mock 异步生成器方法。"""
    async def _gen():
        for item in items:
            yield item
    return _gen()


# === 测试 ===


pytestmark = pytest.mark.bilibili


class TestBiliParseRoute:
    """B 站链接解析路由测试。"""

    def test_parse_video_success(self, api_client: TestClient) -> None:
        """解析视频链接成功。"""
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        parsed = _parsed_video("BV1xx411c7mD")
        ctx.bili_url_parser.parse.return_value = parsed
        ctx.bili_video_parser.parse_video.return_value = _video_info("BV1xx411c7mD")

        response = api_client.post("/api/bilibili/parse", json={"urls": [url]})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["bvid"] == "BV1xx411c7mD"
        assert data[0]["title"] == "测试视频标题"
        assert data[0]["author"] == "测试UP主"
        assert data[0]["author_mid"] == 12345
        assert data[0]["cover_url"] == "https://i0.hdslb.com/bfs/archive/cover.jpg"
        assert data[0]["duration"] == 300
        assert data[0]["view_count"] == 10000
        assert data[0]["danmaku_count"] == 500
        assert data[0]["publish_time"] == 1700000000
        assert data[0]["tags"] == ["测试", "B站"]
        assert len(data[0]["pages"]) == 2
        assert data[0]["pages"][0]["cid"] == 111
        assert data[0]["pages"][1]["page"] == 2

    def test_parse_av_link_success(self, api_client: TestClient) -> None:
        """av 号链接（只有 av_id 无 bvid）也能解析。"""
        url = "https://www.bilibili.com/video/av170001"
        parsed = BiliParsedURL(
            type="video",
            url=url,
            bvid=None,
            av_id=170001,
            mid=None,
            page=1,
        )
        ctx.bili_url_parser.parse.return_value = parsed
        ctx.bili_video_parser.parse_video.return_value = _video_info("BV1xx411c7mD")

        response = api_client.post("/api/bilibili/parse", json={"urls": [url]})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["aid"] == 12345678
        assert data[0]["title"] == "测试视频标题"
        # av 链接应以 aid 传给解析器
        ctx.bili_video_parser.parse_video.assert_awaited_once_with(
            bvid=None, aid=170001, cookie=None
        )

    def test_parse_user_home_success(self, api_client: TestClient) -> None:
        """解析用户主页链接成功。"""
        url = "https://space.bilibili.com/12345"
        parsed = _parsed_user_home(12345)
        ctx.bili_url_parser.parse.return_value = parsed

        response = api_client.post("/api/bilibili/parse", json={"urls": [url]})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["mid"] == 12345
        assert data[0]["bvid"] is None

    def test_parse_video_detail_failure(self, api_client: TestClient) -> None:
        """视频详情解析失败时返回错误信息。"""
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        parsed = _parsed_video("BV1xx411c7mD")
        ctx.bili_url_parser.parse.return_value = parsed
        ctx.bili_video_parser.parse_video.side_effect = RuntimeError("网络错误")

        response = api_client.post("/api/bilibili/parse", json={"urls": [url]})

        assert response.status_code == 200
        data = response.json()
        assert data[0]["bvid"] == "BV1xx411c7mD"
        assert "网络错误" in data[0]["error"]
        assert data[0]["title"] is None

    def test_parse_batch_limit(self, api_client: TestClient) -> None:
        """超过批量限制时返回 400。"""
        urls = [f"https://www.bilibili.com/video/BV{i:010d}" for i in range(51)]
        response = api_client.post("/api/bilibili/parse", json={"urls": urls})
        assert response.status_code == 400
        assert "50" in response.json()["detail"]

    def test_parse_multiple_urls(self, api_client: TestClient) -> None:
        """批量解析多个链接。"""
        urls = [
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://www.bilibili.com/video/BV1yy411c7mE",
        ]
        ctx.bili_url_parser.parse.side_effect = [
            _parsed_video("BV1xx411c7mD"),
            _parsed_video("BV1yy411c7mE"),
        ]
        ctx.bili_video_parser.parse_video.side_effect = [
            _video_info("BV1xx411c7mD"),
            _video_info("BV1yy411c7mE"),
        ]

        response = api_client.post("/api/bilibili/parse", json={"urls": urls})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["bvid"] == "BV1xx411c7mD"
        assert data[1]["bvid"] == "BV1yy411c7mE"

    def test_parse_with_cookie(self, api_client: TestClient) -> None:
        """传入 Cookie 时按每请求参数传递给解析器（不写入共享客户端）。"""
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        parsed = _parsed_video("BV1xx411c7mD")
        ctx.bili_url_parser.parse.return_value = parsed
        ctx.bili_video_parser.parse_video.return_value = _video_info("BV1xx411c7mD")

        response = api_client.post(
            "/api/bilibili/parse",
            json={"urls": [url], "bilibili_cookie": "buvid3=test; SESSDATA=test"},
        )

        assert response.status_code == 200
        # Cookie 通过每请求参数传递，不再修改共享客户端状态
        ctx.bili_http_client.set_cookie.assert_not_called()
        ctx.bili_video_parser.parse_video.assert_awaited_once_with(
            bvid="BV1xx411c7mD", aid=12345678, cookie="buvid3=test; SESSDATA=test"
        )

    def test_parse_unrecognized_url(self, api_client: TestClient) -> None:
        """无法识别的 URL 返回错误信息。"""
        url = "https://example.com/unknown"
        parsed = BiliParsedURL(
            type="video",
            url=url,
            bvid=None,
            av_id=None,
            mid=None,
            page=1,
        )
        ctx.bili_url_parser.parse.return_value = parsed

        response = api_client.post("/api/bilibili/parse", json={"urls": [url]})

        assert response.status_code == 200
        data = response.json()
        assert "无法识别的链接类型" in data[0]["error"]

    def test_parse_service_unavailable(self, api_client: TestClient) -> None:
        """服务未初始化时返回 503。"""
        ctx.bili_url_parser = None
        ctx.bili_video_parser = None

        response = api_client.post("/api/bilibili/parse", json={"urls": ["https://www.bilibili.com/video/BV1xx411c7mD"]})

        assert response.status_code == 503
        assert "B 站服务未初始化" in response.json()["detail"]


class TestBiliPlayUrlRoute:
    """B 站播放流获取路由测试。"""

    def test_playurl_dash_success(self, api_client: TestClient) -> None:
        """获取 DASH 播放流成功。"""
        ctx.bili_video_parser.parse_playurl.return_value = _playurl_result()

        response = api_client.post(
            "/api/bilibili/playurl",
            json={"bvid": "BV1xx411c7mD", "cid": 111, "quality": 80},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["bvid"] == "BV1xx411c7mD"
        assert data["cid"] == 111
        assert data["quality"] == 80
        assert data["quality_name"] == "1080P"
        assert data["dash"] is True
        assert len(data["video_streams"]) == 1
        assert data["video_streams"][0]["width"] == 1920
        assert data["video_streams"][0]["height"] == 1080
        assert len(data["audio_streams"]) == 1
        assert data["audio_streams"][0]["mime_type"] == "audio/mp4"
        assert data["duration"] == 300

    def test_playurl_flv_success(self, api_client: TestClient) -> None:
        """获取非 DASH（FLV）播放流成功。"""
        ctx.bili_video_parser.parse_playurl.return_value = _playurl_flv_result()

        response = api_client.post(
            "/api/bilibili/playurl",
            json={"bvid": "BV1xx411c7mD", "cid": 222},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["dash"] is False
        assert data["video_streams"] == []
        assert data["audio_streams"] == []
        assert data["url"] == "https://upos-bilibili.com/video.flv"

    def test_playurl_bili_api_error(self, api_client: TestClient) -> None:
        """B 站 API 返回错误时转化为 400。"""
        ctx.bili_video_parser.parse_playurl.side_effect = BiliAPIError(
            code=-400, message="请求参数错误"
        )

        response = api_client.post(
            "/api/bilibili/playurl",
            json={"bvid": "BV1xx411c7mD", "cid": 999},
        )

        assert response.status_code == 400
        assert "B 站 API 错误" in response.json()["detail"]

    def test_playurl_generic_error(self, api_client: TestClient) -> None:
        """通用异常时返回 500。"""
        ctx.bili_video_parser.parse_playurl.side_effect = RuntimeError("连接超时")

        response = api_client.post(
            "/api/bilibili/playurl",
            json={"bvid": "BV1xx411c7mD", "cid": 111},
        )

        assert response.status_code == 500
        assert "播放流获取失败" in response.json()["detail"]

    def test_playurl_service_unavailable(self, api_client: TestClient) -> None:
        """服务未初始化时返回 503。"""
        ctx.bili_video_parser = None

        response = api_client.post(
            "/api/bilibili/playurl",
            json={"bvid": "BV1xx411c7mD", "cid": 111},
        )

        assert response.status_code == 503
        assert "B 站服务未初始化" in response.json()["detail"]


class TestBiliFetchSpaceRoute:
    """B 站用户主页抓取路由测试。"""

    def _mock_posts(self):
        """构造两个投稿条目。"""
        return [
            MagicMock(
                bvid="BV1aa",
                aid=1001,
                title="视频1",
                author="UP主",
                cover_url="https://i0.hdslb.com/bfs/cover1.jpg",
                duration=120,
                view_count=1000,
                danmaku_count=50,
                pubdate=1700000000,
                description="描述1",
            ),
            MagicMock(
                bvid="BV1bb",
                aid=1002,
                title="视频2",
                author="UP主",
                cover_url="https://i0.hdslb.com/bfs/cover2.jpg",
                duration=300,
                view_count=2000,
                danmaku_count=100,
                pubdate=1700000001,
                description="描述2",
            ),
        ]

    def test_fetch_space_by_mid(self, api_client: TestClient) -> None:
        """通过 mid 抓取用户主页成功。"""
        posts = self._mock_posts()
        ctx.bili_user_crawler.fetch_user_posts_with_meta.return_value = (posts, False, 2)

        response = api_client.post(
            "/api/bilibili/fetch-space",
            json={"url": "https://space.bilibili.com/12345", "mid": 12345, "max_count": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is False  # total=2 < max_count(10)
        assert data["total"] == 2
        # 前后端契约字段
        item = data["items"][0]
        assert item["bvid"] == "BV1aa"
        assert item["title"] == "视频1"
        assert item["url"] == "https://www.bilibili.com/video/BV1aa"
        assert item["type"] == "video"
        assert item["publish_time"] == 1700000000
        assert item["duration"] == 120

    def test_fetch_space_by_url(self, api_client: TestClient) -> None:
        """通过 URL 解析 mid 后抓取成功。"""
        ctx.bili_url_parser.parse.return_value = _parsed_user_home(67890)

        posts = [MagicMock(bvid="BV1cc", aid=1003, title="视频3", author="UP主", cover_url="", duration=60, view_count=100, danmaku_count=5, pubdate=1700000002, description="描述3")]
        ctx.bili_user_crawler.fetch_user_posts_with_meta.return_value = (posts, True, 50)

        response = api_client.post(
            "/api/bilibili/fetch-space",
            json={"url": "https://space.bilibili.com/67890", "max_count": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["has_more"] is True
        assert data["total"] == 50

    def test_fetch_space_max_count_bounds(self, api_client: TestClient) -> None:
        """max_count 超出边界时返回 422（Field ge/le 约束）。"""
        response = api_client.post(
            "/api/bilibili/fetch-space",
            json={"url": "https://space.bilibili.com/12345", "mid": 12345, "max_count": 0},
        )
        assert response.status_code == 422

        response = api_client.post(
            "/api/bilibili/fetch-space",
            json={"url": "https://space.bilibili.com/12345", "mid": 12345, "max_count": 101},
        )
        assert response.status_code == 422

    def test_fetch_space_no_mid_found(self, api_client: TestClient) -> None:
        """无法解析 mid 时返回 400。"""
        parsed = BiliParsedURL(type="video", url="https://example.com", bvid=None, av_id=None, mid=None, page=1)
        ctx.bili_url_parser.parse.return_value = parsed

        response = api_client.post(
            "/api/bilibili/fetch-space",
            json={"url": "https://example.com", "max_count": 10},
        )

        assert response.status_code == 400
        assert "无法从 URL 解析用户 ID" in response.json()["detail"]

    def test_fetch_space_api_error(self, api_client: TestClient) -> None:
        """B 站 API 错误时返回 400。"""
        ctx.bili_user_crawler.fetch_user_posts_with_meta.side_effect = BiliAPIError(
            code=-412, message="被拦截"
        )

        response = api_client.post(
            "/api/bilibili/fetch-space",
            json={"url": "https://space.bilibili.com/12345", "mid": 12345},
        )

        assert response.status_code == 400
        assert "B 站 API 错误" in response.json()["detail"]

    def test_fetch_space_service_unavailable(self, api_client: TestClient) -> None:
        """服务未初始化时返回 503。"""
        ctx.bili_user_crawler = None
        ctx.bili_url_parser = None

        response = api_client.post(
            "/api/bilibili/fetch-space",
            json={"url": "https://space.bilibili.com/12345", "mid": 12345},
        )

        assert response.status_code == 503
        assert "B 站服务未初始化" in response.json()["detail"]


class TestBiliCookieTestRoute:
    """B 站 Cookie 测试路由测试。"""

    def test_cookie_test_valid(self, api_client: TestClient) -> None:
        """有效 Cookie 返回登录状态。"""
        ctx.bili_http_client.get_json.return_value = {
            "isLogin": True,
            "data": {"uname": "测试用户"},
        }

        response = api_client.post(
            "/api/bilibili/cookie-test",
            json={"cookie": "buvid3=test; SESSDATA=valid"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["nickname"] == "测试用户"
        assert data["message"] == ""
        ctx.bili_signer.refresh_keys.assert_called_once()
        # Cookie 以每请求参数传递，不污染共享客户端
        ctx.bili_http_client.set_cookie.assert_not_called()
        ctx.bili_http_client.get_json.assert_awaited_with(
            "https://api.bilibili.com/x/web-interface/nav",
            signed=False,
            cookie="buvid3=test; SESSDATA=valid",
        )

    def test_cookie_test_invalid(self, api_client: TestClient) -> None:
        """失效 Cookie 返回未登录状态。"""
        ctx.bili_http_client.get_json.return_value = {
            "isLogin": False,
        }

        response = api_client.post(
            "/api/bilibili/cookie-test",
            json={"cookie": "buvid3=test; SESSDATA=expired"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["nickname"] is None
        assert "Cookie 未登录或已失效" in data["message"]

    def test_cookie_test_api_error(self, api_client: TestClient) -> None:
        """接口错误时返回 valid=False。"""
        ctx.bili_http_client.get_json.side_effect = BiliAPIError(
            code=-403, message="禁止访问"
        )

        response = api_client.post(
            "/api/bilibili/cookie-test",
            json={"cookie": "buvid3=test"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "接口错误" in data["message"]

    def test_cookie_test_generic_error(self, api_client: TestClient) -> None:
        """通用异常时返回 valid=False。"""
        ctx.bili_http_client.get_json.side_effect = RuntimeError("网络断开")

        response = api_client.post(
            "/api/bilibili/cookie-test",
            json={"cookie": "buvid3=test"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "测试失败" in data["message"]

    def test_cookie_test_service_unavailable(self, api_client: TestClient) -> None:
        """服务未初始化时返回 503。"""
        ctx.bili_http_client = None
        ctx.bili_signer = None

        response = api_client.post(
            "/api/bilibili/cookie-test",
            json={"cookie": "buvid3=test"},
        )

        assert response.status_code == 503
        assert "B 站服务未初始化" in response.json()["detail"]
