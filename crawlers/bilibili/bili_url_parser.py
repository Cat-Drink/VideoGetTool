"""B 站链接解析器模块。

从用户粘贴的分享文本中提取 B 站链接，识别链接类型，解析出视频 bvid，
用户空间 mid 等关键标识。短链（b23.tv）通过注入的 HttpClient 跟随重定向。

支持识别的链接类型：
    - 视频: https://www.bilibili.com/video/BV1GJ411x7h/ 或 /video/av12345
    - 视频附带分P: ?p=2（多P视频的指定分P）
    - 用户空间: https://space.bilibili.com/12345 或 /12345/video
    - 短链: https://b23.tv/xxxxx（需跟随重定向）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlparse

from crawlers.exceptions import InvalidURLFormatError

if TYPE_CHECKING:
    from httpx import AsyncClient

# === 类型别名 ===

BiliLinkType = Literal["video", "user_home"]


# === 模块级常量 ===

# 通用 URL 提取正则（与 crawlers/url_parser.py 一致）
_URL_PATTERN: re.Pattern[str] = re.compile(
    r"https?://[^\s，。、！？,;；)）\]]+",
    re.IGNORECASE,
)

# B 站合法域名集合
_BILI_DOMAINS: tuple[str, ...] = (
    "www.bilibili.com",
    "bilibili.com",
    "b23.tv",
    "space.bilibili.com",
    "m.bilibili.com",
)

# BV 号正则: BV 开头 + 9~10 位 [0-9A-Za-z]（区分大小写）
# B 站 BV 号总长 11~12 字符（BV 前缀 + 9~10 位），如 BV1GJ411x7h / BV1xx411c7mD
_BVID_PATTERN: re.Pattern[str] = re.compile(r"BV[0-9A-Za-z]{9,10}")

# av 号正则
_AV_PATTERN: re.Pattern[str] = re.compile(r"av(\d+)", re.IGNORECASE)

# 用户空间 mid 正则
_MID_PATTERN: re.Pattern[str] = re.compile(r"space\.bilibili\.com/(\d+)")


@dataclass(frozen=True)
class BiliParsedURL:
    """B 站链接解析结果。

    type == 'video' 时 bvid 必填（支持 av 号自动转换场景）；
    type == 'user_home' 时 mid 必填。

    属性:
        type: 链接类型（'video' / 'user_home'）。
        url: 原始 URL（或重定向后的最终 URL）。
        bvid: B 站视频 BV 号。
        av_id: 视频 av 号（int），从 av 链接提取。
        mid: 用户空间 ID（int）。
        page: 分P页码（1 起），无分P参数时为 1。
        original_text: 原始文本。
    """

    type: BiliLinkType
    url: str
    bvid: str | None = None
    av_id: int | None = None
    mid: int | None = None
    page: int = 1
    original_text: str = ""


class BiliURLParser:
    """B 站链接解析器。

    纯逻辑组件，不持有网络连接；如需跟随 b23.tv 短链重定向，
    通过注入的 httpx.AsyncClient 完成。
    """

    def __init__(self, http_client: AsyncClient | None = None) -> None:
        """初始化链接解析器。

        参数:
            http_client: 用于跟随短链重定向的 httpx 客户端（可选）。
        """
        self._http_client = http_client

    # === 链接提取 ===

    def extract_url(self, text: str) -> str | None:
        """从任意文本中提取第一个 B 站链接 URL。

        参数:
            text: 原始文本（可能含分享口令上下文）。

        返回:
            提取到的 URL 字符串；未找到返回 None。
        """
        if not text:
            return None
        for match in _URL_PATTERN.finditer(text):
            url = match.group(0)
            url = url.rstrip(".,;:)]}。，；：）】》")
            if self._is_bili_url(url):
                return url
        return None

    @staticmethod
    def _is_bili_url(url: str) -> bool:
        """判断 URL 是否属于 B 站合法域名。"""
        url_lower = url.lower()
        host_match = re.match(r"https?://([^/]+)/?", url_lower)
        if not host_match:
            return False
        host = host_match.group(1).split(":")[0]
        return host in _BILI_DOMAINS

    # === ID 提取（静态方法，可独立调用） ===

    @staticmethod
    def extract_bvid(url: str) -> str | None:
        """从 URL 中提取 BV 号。

        参数:
            url: B 站链接。

        返回:
            BV 号字符串（如 "BV1GJ411x7h"）；未找到返回 None。
        """
        match = _BVID_PATTERN.search(url)
        return match.group(0) if match else None

    @staticmethod
    def extract_av_id(url: str) -> int | None:
        """从 URL 中提取 av 号。

        参数:
            url: B 站链接。

        返回:
            av 号整数；未找到返回 None。
        """
        match = _AV_PATTERN.search(url)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def extract_mid(url: str) -> int | None:
        """从 URL 中提取用户空间 mid（纯数字 ID）。

        参数:
            url: B 站空间链接。

        返回:
            mid 整数；未找到返回 None。
        """
        match = _MID_PATTERN.search(url)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def extract_page(url: str) -> int:
        """从 URL 查询参数中提取分P页码。

        参数:
            url: B 站链接（可能含 ?p=N 参数）。

        返回:
            分P页数（1 起）；无参数或非法时返回 1。
        """
        try:
            parsed = urlparse(url)
            query = parse_qs(parsed.query or "")
            p_values = query.get("p") or query.get("page") or []
            if p_values:
                page = int(p_values[0])
                if page >= 1:
                    return page
        except (ValueError, TypeError):
            pass
        return 1

    # === 类型识别 ===

    def identify_type(self, url: str) -> BiliLinkType:
        """根据 URL 路径识别链接类型。

        识别规则（按优先级）:
            1. 路径含 `/video/` 或提取到 BV 号 / av 号 → `'video'`
            2. 路径含 `/space/` 或提取到 mid → `'user_home'`
            3. 其他 → 抛 InvalidURLFormatError

        参数:
            url: 已规范化的 URL。

        返回:
            'video' 或 'user_home'。

        异常:
            InvalidURLFormatError: 无法从 URL 识别类型。
        """
        try:
            parsed = urlparse(url)
        except ValueError as e:
            raise InvalidURLFormatError(f"URL 格式无效: {url}") from e

        path = parsed.path or ""
        bvid = self.extract_bvid(url)
        av_id = self.extract_av_id(url)
        mid = self.extract_mid(url)

        # 规则 1：视频
        if bvid or av_id or "/video/" in path:
            return "video"

        # 规则 2：用户空间
        if mid or "/space/" in path:
            return "user_home"

        raise InvalidURLFormatError(f"无法识别的 B 站链接类型: {url}")

    # === 完整解析流程 ===

    async def parse(self, text: str) -> BiliParsedURL:
        """完整解析一条分享文本。

        流程:
            1. extract_url 提取 URL
            2. 若为 b23.tv 短链，跟随重定向获取最终 URL
            3. identify_type 识别类型
            4. 提取 bvid / av_id / mid / page，构造结果

        参数:
            text: 分享文本。

        返回:
            BiliParsedURL 实例。

        异常:
            InvalidURLFormatError: 文本中无 B 站链接或类型无法识别。
        """
        url = self.extract_url(text)
        if url is None:
            raise InvalidURLFormatError(f"未在文本中找到 B 站链接: {text[:50]}")

        # 短链跟随重定向
        if "b23.tv" in url or "m.bilibili.com/short" in url:
            url = await self._follow_redirect(url)

        link_type = self.identify_type(url)
        bvid = self.extract_bvid(url)
        av_id = self.extract_av_id(url)
        mid = self.extract_mid(url)
        page = self.extract_page(url)

        return BiliParsedURL(
            type=link_type,
            url=url,
            bvid=bvid,
            av_id=av_id,
            mid=mid,
            page=page,
            original_text=text,
        )

    async def _follow_redirect(self, url: str) -> str:
        """跟随短链重定向获取最终 URL。

        使用 GET 跟随重定向；为防止 SSRF，落地 URL 的 host 必须属于
        _BILI_DOMAINS 白名单，否则回退到原 URL（由上层解析器反馈失败）。

        参数:
            url: 短链 URL。

        返回:
            最终 URL（host 校验通过）；校验失败或网络异常时返回原 URL。
        """
        if self._http_client is None:
            return url
        try:
            resp = await self._http_client.get(url, follow_redirects=True)
            final_url = str(resp.url)
            final_host = (urlparse(final_url).hostname or "").lower()
            if final_host not in _BILI_DOMAINS:
                # 非 B 站域名（可能被重定向到内网/元数据地址），拒绝跟随
                return url
            return final_url
        except Exception:
            # 网络异常时返回原 URL，由上层解析器反馈失败
            return url
