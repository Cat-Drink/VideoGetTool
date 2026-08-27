"""B 站爬虫包入口。

聚合导出所有公开类，保持与项目 crawlers/ 同级包一致的导入风格。

使用方式::

    from crawlers.bilibili import (
        BiliSigner,
        BiliURLParser,
        BiliVideoParser,
        BiliUserCrawler,
        BiliHttpClient,
    )

    signer = BiliSigner()
    client = BiliHttpClient(signer)
    parser = BiliVideoParser(client, signer)
    info = await parser.parse_video("BV1GJ411x7h")
"""

from __future__ import annotations

from crawlers.bilibili.bili_http_client import BiliAPIError, BiliHttpClient
from crawlers.bilibili.bili_signer import BiliSigner
from crawlers.bilibili.bili_url_parser import BiliParsedURL, BiliURLParser
from crawlers.bilibili.bili_user_crawler import BiliPostItem, BiliUserCrawler
from crawlers.bilibili.bili_video_parser import (
    BiliPage,
    BiliPlayUrl,
    BiliStream,
    BiliVideoInfo,
    BiliVideoParser,
)

__all__ = [
    "BiliAPIError",
    "BiliHttpClient",
    "BiliPage",
    "BiliParsedURL",
    "BiliPlayUrl",
    "BiliPostItem",
    "BiliSigner",
    "BiliStream",
    "BiliURLParser",
    "BiliUserCrawler",
    "BiliVideoInfo",
    "BiliVideoParser",
]
