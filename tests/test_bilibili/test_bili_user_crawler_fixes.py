"""B 站用户主页抓取器与 URL 解析器修复相关测试。

覆盖：
    - vlist 嵌套结构（data.list.vlist）解析（P1-4）
    - 投稿时长 "MM:SS" 字符串转秒（P1-5）
    - fetch_user_posts_with_meta 的 has_more / total（P2-5）
    - max_count 越界钳制（P1-12）
    - 短链重定向 SSRF 防护（P1-13）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crawlers.bilibili.bili_url_parser import BiliURLParser
from crawlers.bilibili.bili_user_crawler import BiliPostItem, BiliUserCrawler, _parse_duration

pytestmark = pytest.mark.bilibili


# === _parse_duration ===


class TestParseDuration:
    """投稿时长字段解析测试。"""

    def test_mmss_string(self) -> None:
        """'MM:SS' 字符串转秒。"""
        assert _parse_duration("12:34") == 754

    def test_hmmss_string(self) -> None:
        """'H:MM:SS' 字符串转秒。"""
        assert _parse_duration("1:02:03") == 3723

    def test_seconds_int(self) -> None:
        """秒数字段直接返回。"""
        assert _parse_duration(300) == 300
        assert _parse_duration(0) == 0

    def test_numeric_string(self) -> None:
        """纯数字字符串转 int。"""
        assert _parse_duration("120") == 120

    def test_invalid_string(self) -> None:
        """非法字符串回退为 0。"""
        assert _parse_duration("abc") == 0
        assert _parse_duration("1:xx") == 0


# === BiliUserCrawler ===


def _make_crawler() -> tuple[BiliUserCrawler, MagicMock]:
    """构造带 mock http_client 的抓取器。"""
    http_client = MagicMock(name="BiliHttpClient")
    http_client.get_json = AsyncMock(name="get_json")
    signer = MagicMock(name="BiliSigner")
    return BiliUserCrawler(http_client, signer), http_client


def _page_data(vlist: list[dict], count: int) -> dict:
    """构造 arc/search 响应 data（data.list.vlist 嵌套结构）。"""
    return {"page": {"count": count}, "list": {"vlist": vlist}}


class TestUserCrawlerVlist:
    """投稿列表 vlist 嵌套结构解析测试。"""

    @pytest.mark.asyncio
    async def test_vlist_nested_structure(self) -> None:
        """data.list.vlist 嵌套结构能正确解析出投稿。"""
        crawler, http_client = _make_crawler()
        http_client.get_json.return_value = _page_data(
            [
                {
                    "bvid": "BV1aa",
                    "aid": 1001,
                    "title": "视频1",
                    "author": "UP主",
                    "pic": "cover.jpg",
                    "length": "5:30",
                    "play": 999,
                    "danmaku": 88,
                    "pubdate": 1700000000,
                    "description": "描述",
                    "mid": 12345,
                }
            ],
            count=1,
        )

        items, has_more, total = await crawler.fetch_user_posts_with_meta(12345, max_count=10)

        assert len(items) == 1
        item = items[0]
        assert isinstance(item, BiliPostItem)
        assert item.bvid == "BV1aa"
        assert item.duration == 330  # "5:30" → 330 秒
        assert item.view_count == 999
        assert item.pubdate == 1700000000
        assert has_more is False
        assert total == 1

    @pytest.mark.asyncio
    async def test_vlist_flat_fallback(self) -> None:
        """无 list 嵌套时回退到顶层 vlist。"""
        crawler, http_client = _make_crawler()
        http_client.get_json.return_value = {
            "page": {"count": 1},
            "vlist": [
                {
                    "bvid": "BV1bb",
                    "aid": 1002,
                    "title": "视频2",
                    "author": "UP",
                    "pic": "",
                    "length": "1:00",
                    "play": 1,
                    "danmaku": 0,
                    "pubdate": 0,
                }
            ],
        }

        items, has_more, total = await crawler.fetch_user_posts_with_meta(12345, max_count=10)

        assert len(items) == 1
        assert items[0].bvid == "BV1bb"
        assert items[0].duration == 60

    @pytest.mark.asyncio
    async def test_has_more_uses_real_total(self) -> None:
        """has_more 依据真实总数而非 len>=max_count 近似判断。"""
        crawler, http_client = _make_crawler()
        # 第一页 30 条，真实总数 80 → has_more=True
        vlist = [
            {
                "bvid": f"BV{i:02d}",
                "aid": i,
                "title": f"v{i}",
                "author": "UP",
                "pic": "",
                "length": "1:00",
                "play": 0,
                "danmaku": 0,
                "pubdate": 0,
            }
            for i in range(30)
        ]
        http_client.get_json.side_effect = [
            _page_data(vlist, count=80),  # 第一页
            _page_data(vlist, count=80),  # 第二页
            _page_data(vlist, count=80),  # 第三页
        ]

        items, has_more, total = await crawler.fetch_user_posts_with_meta(12345, max_count=100)

        assert len(items) == 80
        assert has_more is False  # 拉满真实总数 80 条，无更多
        assert total == 80

    @pytest.mark.asyncio
    async def test_max_count_clamped_to_100(self) -> None:
        """max_count 超过 100 时被钳制到 100。"""
        crawler, http_client = _make_crawler()
        vlist = [
            {
                "bvid": f"BV{i:03d}",
                "aid": i,
                "title": f"v{i}",
                "author": "UP",
                "pic": "",
                "length": "0:05",
                "play": 0,
                "danmaku": 0,
                "pubdate": 0,
            }
            for i in range(30)
        ]
        http_client.get_json.side_effect = [
            _page_data(vlist, count=300),
            _page_data(vlist, count=300),
            _page_data(vlist, count=300),
            _page_data(vlist, count=300),
        ]

        items, has_more, total = await crawler.fetch_user_posts_with_meta(12345, max_count=999)

        assert len(items) == 100
        assert has_more is True  # total=300 > 100
        assert total == 300

    @pytest.mark.asyncio
    async def test_fetch_user_posts_generator(self) -> None:
        """旧生成器接口 fetch_user_posts 仍可用。"""
        crawler, http_client = _make_crawler()
        http_client.get_json.return_value = _page_data(
            [
                {
                    "bvid": "BV1cc",
                    "aid": 1003,
                    "title": "视频3",
                    "author": "UP",
                    "pic": "",
                    "length": "2:00",
                    "play": 5,
                    "danmaku": 1,
                    "pubdate": 1,
                }
            ],
            count=1,
        )

        posts = [post async for post in crawler.fetch_user_posts(12345, max_count=10)]

        assert len(posts) == 1
        assert posts[0].bvid == "BV1cc"
        assert posts[0].duration == 120


# === URL 解析器 SSRF ===


class TestURLParserSSRF:
    """短链重定向 SSRF 防护测试。"""

    @pytest.mark.asyncio
    async def test_redirect_to_bili_domain_accepted(self) -> None:
        """重定向到 B 站域名时接受最终 URL（302 → 200 两段式）。"""
        http_client = MagicMock()
        resp_302 = MagicMock()
        resp_302.status_code = 302
        resp_302.headers = {"location": "https://www.bilibili.com/video/BV1xx411c7mD"}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.url = "https://www.bilibili.com/video/BV1xx411c7mD"
        http_client.get = AsyncMock(side_effect=[resp_302, resp_200])
        parser = BiliURLParser(http_client=http_client)

        result = await parser._follow_redirect("https://b23.tv/abc")

        assert result == "https://www.bilibili.com/video/BV1xx411c7mD"

    @pytest.mark.asyncio
    async def test_redirect_to_non_bili_rejected(self) -> None:
        """重定向到非 B 站域名（内网/元数据地址）时回退原 URL，且不发后续请求。"""
        http_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 302
        resp.headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        http_client.get = AsyncMock(return_value=resp)
        parser = BiliURLParser(http_client=http_client)

        result = await parser._follow_redirect("https://b23.tv/evil")

        assert result == "https://b23.tv/evil"
        # 只发起一跳请求，未对非法主机发出请求
        assert http_client.get.await_count == 1

    @pytest.mark.asyncio
    async def test_redirect_network_error_fallback(self) -> None:
        """网络异常时回退原 URL。"""
        http_client = MagicMock()
        http_client.get = AsyncMock(side_effect=RuntimeError("network down"))
        parser = BiliURLParser(http_client=http_client)

        result = await parser._follow_redirect("https://b23.tv/abc")

        assert result == "https://b23.tv/abc"
