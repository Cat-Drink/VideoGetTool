"""爬虫 API 路由集成测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.state import ctx
from crawlers.url_parser import ParsedURL
from crawlers.user_home_crawler import PostItem
from crawlers.video_parser import VideoInfo


@pytest.fixture
def api_client() -> TestClient:
    """创建只挂载 crawler router 的 TestClient，并隔离全局上下文。"""
    from backend.api.crawler import router

    ctx_fields = ("url_parser", "video_parser", "user_home_crawler", "cookie_repo")
    previous = {field: getattr(ctx, field) for field in ctx_fields}

    url_parser = MagicMock(name="URLParser")
    url_parser.parse = AsyncMock(name="URLParser.parse")
    video_parser = MagicMock(name="VideoParser")
    video_parser.parse_video = AsyncMock(name="VideoParser.parse_video")
    user_home_crawler = MagicMock(name="UserHomeCrawler")

    ctx.url_parser = url_parser
    ctx.video_parser = video_parser
    ctx.user_home_crawler = user_home_crawler
    ctx.cookie_repo = None

    app = FastAPI()
    app.include_router(router, prefix="/api/crawler")
    client = TestClient(app)
    try:
        yield client
    finally:
        for field, value in previous.items():
            setattr(ctx, field, value)


def _parsed_video(url: str, aweme_id: str) -> ParsedURL:
    """构造视频 URL 解析结果。"""
    return ParsedURL(
        type="video",
        url=url,
        aweme_id=aweme_id,
        sec_user_id=None,
        original_text=url,
    )


def _video_info(aweme_id: str = "aweme-1") -> VideoInfo:
    """构造视频详情解析结果。"""
    return VideoInfo(
        aweme_id=aweme_id,
        type="video",
        title="测试视频",
        author="测试作者",
        author_sec_id="sec-author",
        duration="15s",
        cover_url="https://example.com/cover.jpg",
        no_watermark_url="https://example.com/video.mp4",
        image_urls=[],
        publish_time="2026-01-01T00:00:00Z",
        like_count=1,
        comment_count=2,
        share_count=3,
        collect_count=4,
        tags=["测试"],
        raw_json={"aweme_id": aweme_id},
    )


class TestParseRoute:
    """批量解析路由测试。"""

    def test_parse_maps_success_and_keeps_detail_failure(self, api_client: TestClient) -> None:
        """详情解析失败只影响当前结果，批次仍返回 200。"""
        from backend.state import ctx

        first_url = "https://www.douyin.com/video/1001"
        second_url = "https://www.douyin.com/vsdetail/1002"
        ctx.url_parser.parse.side_effect = [
            _parsed_video(first_url, "1001"),
            _parsed_video(second_url, "1002"),
        ]
        ctx.video_parser.parse_video.side_effect = [
            _video_info("1001"),
            RuntimeError("detail unavailable"),
        ]

        response = api_client.post("/api/crawler/parse", json={"urls": [first_url, second_url]})

        assert response.status_code == 200
        data = response.json()
        assert [item["url"] for item in data] == [first_url, second_url]
        assert data[0]["title"] == "测试视频"
        assert data[0]["no_watermark_url"].endswith("video.mp4")
        assert data[1]["aweme_id"] == "1002"
        assert "视频详情解析失败" in data[1]["error"]
        assert "直播回放" in data[1]["error"]

        too_many = api_client.post(
            "/api/crawler/parse",
            json={"urls": [f"https://www.douyin.com/video/{i}" for i in range(51)]},
        )
        assert too_many.status_code == 400
        assert "最多 50 个链接" in too_many.json()["detail"]


class TestFetchHomeRoute:
    """主页抓取路由测试。"""

    def test_fetch_home_maps_items_and_rejects_non_home_url(
        self, api_client: TestClient
    ) -> None:
        """主页作品映射正确，并拒绝非主页 URL。"""
        from backend.state import ctx

        home_url = "https://www.douyin.com/user/sec-home"
        ctx.url_parser.parse.return_value = ParsedURL(
            type="user_home",
            url=home_url,
            aweme_id=None,
            sec_user_id="sec-home",
            original_text=home_url,
        )
        posts = [
            PostItem(
                aweme_id="post-1",
                title="第一条",
                author="作者A",
                author_sec_id="sec-author",
                cover_url="https://example.com/1.jpg",
                type="video",
                create_time="2026-01-01T00:00:00Z",
                duration="15s",
                image_count=None,
            ),
            PostItem(
                aweme_id="post-2",
                title="第二条",
                author="作者A",
                author_sec_id="sec-author",
                cover_url="https://example.com/2.jpg",
                type="image_set",
                create_time="2026-01-02T00:00:00Z",
                duration=None,
                image_count=3,
            ),
        ]

        async def iter_posts(*args, **kwargs):
            for post in posts:
                yield post

        ctx.user_home_crawler.fetch_user_posts = MagicMock(side_effect=iter_posts)

        response = api_client.post(
            "/api/crawler/fetch-home",
            json={"url": home_url, "max_items": 2},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["has_more"] is True
        assert data["items"][0]["url"].endswith("/post-1")
        assert data["items"][1]["image_count"] == 3
        filters = ctx.user_home_crawler.fetch_user_posts.call_args.args[1]
        assert filters.type_filter == "all"
        assert filters.max_count == 2

        ctx.url_parser.parse.return_value = _parsed_video(home_url, "not-home")
        invalid = api_client.post(
            "/api/crawler/fetch-home",
            json={"url": home_url, "max_items": 2},
        )
        assert invalid.status_code == 400
        assert invalid.json()["detail"] == "无法从 URL 解析用户主页 ID"


class TestPreviewRoute:
    """预览路由测试。"""

    def test_preview_returns_fallback_error_and_validates_query_parameter(
        self, api_client: TestClient
    ) -> None:
        """详情失败时返回基础信息，缺少查询参数时返回 422。"""
        from backend.state import ctx

        url = "https://www.douyin.com/video/1001"
        ctx.url_parser.parse.return_value = _parsed_video(url, "1001")
        ctx.video_parser.parse_video.side_effect = RuntimeError("detail unavailable")

        response = api_client.post("/api/crawler/preview", params={"url": url})

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == url
        assert data["type"] == "video"
        assert data["aweme_id"] == "1001"
        assert data["error"] == "detail unavailable"
        assert data["title"] is None

        missing_url = api_client.post("/api/crawler/preview")
        assert missing_url.status_code == 422
