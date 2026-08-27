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

import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.logger import get_logger
from crawlers.bilibili.constants import SPACE_ARC_SEARCH_URL, SPACE_PAGE_SIZE

if TYPE_CHECKING:
    from crawlers.bilibili.bili_http_client import BiliHttpClient
    from crawlers.bilibili.bili_signer import BiliSigner

logger = get_logger(__name__)


def _normalize_cover_url(url: str) -> str:
    """归一化封面图片地址为 HTTPS。

    B 站 space 接口返回的 pic 字段常为 http:// 地址；在 Tauri 打包后的
    WebView 中 http 子资源会被当作混合内容拦截，导致封面不显示。
    https 变体经实测可用，因此统一替换为 https。
    """
    if url and url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


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


def _parse_duration(value: object) -> int:
    """把 vlist 条目中的时长字段转换为秒。

    vlist 的 length 字段为 "MM:SS" 字符串，duration 字段为秒数；
    兼容两者，解析失败回退为 0。

    参数:
        value: 原始时长值（str "MM:SS" 或 int/float 秒）。

    返回:
        秒数（int）。
    """
    if isinstance(value, str):
        text = value.strip()
        if ":" in text:
            total = 0
            try:
                for part in text.split(":"):
                    total = total * 60 + int(part)
                return total
            except ValueError:
                return 0
        try:
            return int(float(text))
        except ValueError:
            return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


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
        cookie: str | None = None,
    ) -> AsyncIterator[BiliPostItem]:
        """分页拉取用户投稿列表。

        使用 AsyncIterator 产出，调用方可用 `async for` 消费；
        每页请求后 yield 当前页所有条目。

        参数:
            mid: 用户 ID。
            max_count: 最大拉取数量（1~100，越界时自动钳制）。
            order: 排序方式（pubdate 或 click）。
            cookie: 本次请求使用的 B 站 Cookie（可选），仅当前请求生效。

        产出:
            BiliPostItem 实例。

        异常:
            BiliAPIError: 接口返回业务错误。
            NetworkError: 网络异常。
        """
        async for item, _has_more, _total in self._fetch_pages(mid, max_count, order, cookie):
            yield item

    async def fetch_user_posts_with_meta(
        self,
        mid: int,
        max_count: int = 50,
        order: str = "pubdate",
        cookie: str | None = None,
    ) -> tuple[list[BiliPostItem], bool, int]:
        """分页拉取用户投稿，返回条目列表与真实分页信息。

        与 fetch_user_posts 不同，本方法一次性收集全部条目，并返回：
            (items, has_more, total_count)
        其中 has_more 依据接口真实总数（data.page.count）判断，避免
        “恰好等于 max_count 就误报还有更多”。

        参数:
            mid: 用户 ID。
            max_count: 最大拉取数量（1~100，越界时自动钳制）。
            order: 排序方式（pubdate 或 click）。
            cookie: 本次请求使用的 B 站 Cookie（可选），仅当前请求生效。

        返回:
            (条目列表, 是否还有更多, 接口返回的真实总数)。
        """
        # 一次性收集全部条目，并返回精确的 has_more / total_count
        return await self._collect_pages(mid, max_count, order, cookie)

    async def _collect_pages(
        self,
        mid: int,
        max_count: int,
        order: str,
        cookie: str | None,
    ) -> tuple[list[BiliPostItem], bool, int]:
        """一次性收集全部投稿并返回 (items, has_more, total_count)。

        相比生成器，这里能基于 data.page.count 精确判断 has_more 与真实总数。
        """
        # 钳制 max_count 到 [1, 100]
        limit = max(1, min(int(max_count), 100))
        page = 1
        fetched = 0
        items: list[BiliPostItem] = []
        total_count = 0

        while True:
            params = {
                "mid": mid,
                "ps": SPACE_PAGE_SIZE,
                "pn": page,
                "order": order,
            }

            data = await self._http_client.get_json(
                SPACE_ARC_SEARCH_URL, params, signed=True, cookie=cookie
            )

            if not data:
                break

            # 分页信息：data.page.count 为真实总数
            page_info = data.get("page") or {}
            total_count = page_info.get("count") or 0

            # 实际 API 结构: data.list.vlist（list 为 dict，vlist 为列表）
            list_data = data.get("list") or {}
            vlist = list_data.get("vlist") if isinstance(list_data, dict) else None
            if not isinstance(vlist, list):
                vlist = data.get("vlist") or []
            if not vlist:
                break

            for v in vlist:
                if not isinstance(v, dict):
                    continue
                bvid = v.get("bvid") or ""
                if not bvid:
                    continue
                # API 的 page.count 是真实总数，避免异常/重复响应导致超过总数
                if total_count > 0 and fetched >= total_count:
                    return items, False, total_count

                item = BiliPostItem(
                    bvid=bvid,
                    aid=v.get("aid", 0),
                    title=v.get("title", ""),
                    author=v.get("author", ""),
                    cover_url=_normalize_cover_url(v.get("pic", "")),
                    duration=_parse_duration(v.get("length") or v.get("duration") or 0),
                    view_count=v.get("play", 0) or v.get("view", 0) or 0,
                    danmaku_count=v.get("danmaku", 0) or v.get("video_review", 0) or 0,
                    pubdate=v.get("pubdate", 0),
                    description=v.get("description", ""),
                    mid=v.get("mid", 0),
                )
                items.append(item)
                fetched += 1

                if fetched >= limit:
                    has_more = bool(total_count) and fetched < total_count
                    return items, has_more, total_count

            # 无更多页或达到总页数
            if total_count <= 0:
                break
            total_pages = math.ceil(total_count / SPACE_PAGE_SIZE)
            if page >= total_pages:
                break
            page += 1

        has_more = bool(total_count) and fetched < total_count
        return items, has_more, total_count

    async def _fetch_pages(
        self,
        mid: int,
        max_count: int,
        order: str,
        cookie: str | None,
    ) -> AsyncIterator[tuple[BiliPostItem, bool, int]]:
        """分页产出 (item, has_more, total_count)。

        与 _collect_pages 逻辑一致但逐条产出；
        has_more / total_count 取当前页已获取的信息（接近真实值）。
        """
        limit = max(1, min(int(max_count), 100))
        page = 1
        fetched = 0
        total_count = 0

        while True:
            params = {
                "mid": mid,
                "ps": SPACE_PAGE_SIZE,
                "pn": page,
                "order": order,
            }

            data = await self._http_client.get_json(
                SPACE_ARC_SEARCH_URL, params, signed=True, cookie=cookie
            )

            if not data:
                break

            page_info = data.get("page") or {}
            total_count = page_info.get("count") or 0

            list_data = data.get("list") or {}
            vlist = list_data.get("vlist") if isinstance(list_data, dict) else None
            if not isinstance(vlist, list):
                vlist = data.get("vlist") or []
            if not vlist:
                break

            for v in vlist:
                if not isinstance(v, dict):
                    continue
                bvid = v.get("bvid") or ""
                if not bvid:
                    continue
                # API 的 page.count 是真实总数，避免异常/重复响应导致超过总数
                if total_count > 0 and fetched >= total_count:
                    return

                item = BiliPostItem(
                    bvid=bvid,
                    aid=v.get("aid", 0),
                    title=v.get("title", ""),
                    author=v.get("author", ""),
                    cover_url=_normalize_cover_url(v.get("pic", "")),
                    duration=_parse_duration(v.get("length") or v.get("duration") or 0),
                    view_count=v.get("play", 0) or v.get("view", 0) or 0,
                    danmaku_count=v.get("danmaku", 0) or v.get("video_review", 0) or 0,
                    pubdate=v.get("pubdate", 0),
                    description=v.get("description", ""),
                    mid=v.get("mid", 0),
                )
                fetched += 1
                has_more = bool(total_count) and fetched < total_count
                yield item, has_more, total_count

                if fetched >= limit:
                    return

            if total_count <= 0:
                break
            total_pages = math.ceil(total_count / SPACE_PAGE_SIZE)
            if page >= total_pages:
                break
            page += 1
