"""B 站用户主页抓取器模块。

根据 mid 分页拉取 B 站用户投稿列表，使用 /x/space/wbi/arc/search 接口，
需要 WBI 签名。

接口参数:
    - mid: 用户 ID
    - ps: 每页数量（默认 30，最大 50）
    - pn: 页码（从 1 开始）
    - order: 排序方式（pubdate=发布时间排序, click=播放量排序）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.logger import get_logger
from crawlers.bilibili.constants import SPACE_ARC_SEARCH_URL, SPACE_PAGE_SIZE

if TYPE_CHECKING:
    from crawlers.bilibili.bili_http_client import BiliHttpClient
    from crawlers.bilibili.bili_signer import BiliSigner

logger = get_logger(__name__)


# === 数据结构 ===


@dataclass(frozen=True)
class BiliPostItem:
    """B 站用户空间中的单个作品条目（非完整信息，供 UI 展示勾选）。

    完整信息（含播放流）需通过 BiliVideoParser 二次解析。
    """

    bvid: str
    aid: int
    title: str
    author: str
    cover_url: str
    duration: int  # 秒
    view_count: int
    danmaku_count: int
    pubdate: int  # Unix 秒
    description: str = ""
    mid: int = 0
    type: str = "video"


# === 用户主页抓取器 ===


class BiliUserCrawler:
    """B 站用户主页抓取器。

    调用 /x/space/wbi/arc/search 接口分页拉取用户投稿，
    异步产出 BiliPostItem 流。
    """

    def __init__(
        self,
        http_client: BiliHttpClient,
        signer: BiliSigner,
    ) -> None:
        """初始化用户主页抓取器。

        参数:
            http_client: BiliHttpClient 实例。
            signer: BiliSigner 实例。
        """
        self._http_client = http_client
        self._signer = signer

    async def fetch_user_posts(
        self,
        mid: int,
        max_count: int = 50,
        order: str = "pubdate",
    ) -> AsyncIterator[BiliPostItem]:
        """分页拉取用户投稿列表。

        使用 AsyncIterator 产出，调用方可用 `async for` 消费；
        每页请求后 yield 当前页所有条目。

        参数:
            mid: 用户 ID。
            max_count: 最大拉取数量（0 表示不限）。
            order: 排序方式（pubdate 或 click）。

        产出:
            BiliPostItem 实例。

        异常:
            BiliAPIError: 接口返回业务错误。
            NetworkError: 网络异常。
        """
        page = 1
        fetched = 0

        while True:
            params = {
                "mid": mid,
                "ps": SPACE_PAGE_SIZE,
                "pn": page,
                "order": order,
            }

            data = await self._http_client.get_json(SPACE_ARC_SEARCH_URL, params, signed=True)

            if not data:
                break

            # 解析列表
            vlist = data.get("list") or data.get("vlist") or []
            if not isinstance(vlist, list) or not vlist:
                break

            for v in vlist:
                if not isinstance(v, dict):
                    continue
                bvid = v.get("bvid") or ""
                if not bvid:
                    continue

                item = BiliPostItem(
                    bvid=bvid,
                    aid=v.get("aid", 0),
                    title=v.get("title", ""),
                    author=v.get("author", ""),
                    cover_url=v.get("pic", ""),
                    duration=v.get("length", 0) or v.get("duration", 0) or 0,
                    view_count=v.get("play", 0) or v.get("view", 0) or 0,
                    danmaku_count=v.get("danmaku", 0) or v.get("video_review", 0) or 0,
                    pubdate=v.get("pubdate", 0),
                    description=v.get("description", ""),
                    mid=v.get("mid", 0),
                )
                yield item
                fetched += 1

                # 达到上限时停止
                if max_count > 0 and fetched >= max_count:
                    return

            # 分页信息
            page_info = data.get("page") or {}
            total_pages = page_info.get("count") or 0
            total_pages = (total_pages + SPACE_PAGE_SIZE - 1) // SPACE_PAGE_SIZE  # 最大页数

            if page >= total_pages:
                break

            page += 1
