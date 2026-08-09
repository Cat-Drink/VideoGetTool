"""链接解析器模块。

从用户粘贴的分享文本中提取抖音链接，识别链接类型，解析出作品 ID 或
用户主页 sec_user_id。短链重定向通过注入的 HttpClient 完成。

接口签名与 ``docs/structure/05-接口设计文档.md`` 第 3.1 节保持一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlparse

from crawlers.exceptions import InvalidURLFormatError

if TYPE_CHECKING:
    from crawlers.http_client import HttpClient

# === 类型别名 ===

LinkType = Literal["video", "image_set", "long_video", "user_home"]

# === 模块级常量 ===

# 通用 URL 提取正则：匹配 http(s):// 开头、到空白或中文标点结束的子串
# 中文逗号/句号/顿号/感叹号/问号 作为分隔符，避免吞入分享文本的描述部分
# 注意：英文 ? 与 ! 不作为终止符，因为它们是合法 URL 字符（查询分隔符/sub-delim）
_URL_PATTERN: re.Pattern[str] = re.compile(
    r"https?://[^\s，。、！？,;；)）\]]+",
    re.IGNORECASE,
)

# v0.1.5：抖音短链专用保守匹配正则（用户反馈 #1）
# 仅匹配 https://v.douyin.com/xxx/ 格式，宁可漏匹配也不要错误匹配描述文字
# 用于 extract_short_urls 从分享文本中批量提取短链
_SHORT_URL_PATTERN: re.Pattern[str] = re.compile(
    r"https?://v\.douyin\.com/[A-Za-z0-9]+/?",
    re.IGNORECASE,
)

# 抖音合法域名集合（短链 + 长链）
# - v.douyin.com：分享短链
# - www.douyin.com / douyin.com：长链（视频/主页）
# - iesdouyin.com：旧域名兼容
_DOUYIN_DOMAINS: tuple[str, ...] = (
    "v.douyin.com",
    "www.douyin.com",
    "douyin.com",
    "www.iesdouyin.com",
    "iesdouyin.com",
)


@dataclass(frozen=True)
class ParsedURL:
    """URL 解析结果。

    type 为 'video' | 'image_set' | 'long_video' 时，aweme_id 必填、sec_user_id 为 None。
    type 为 'user_home' 时，sec_user_id 必填、aweme_id 为 None。

    注：image_set 与 long_video 的最终判定依赖 VideoParser 调用 detail 接口后的结果，
        URLParser 仅在能从 URL 直接判断时给出预判，否则默认归为 'video'。
    """

    type: LinkType
    url: str
    aweme_id: str | None
    sec_user_id: str | None
    original_text: str


class URLParser:
    """链接解析器。

    纯逻辑组件，不持有网络连接；如需跟随短链重定向，通过注入的 HttpClient 完成。

    解析流程（parse 方法编排）：
        extract_url → follow_redirect（如需）→ identify_type → 构造 ParsedURL
    """

    def __init__(self, http_client: HttpClient) -> None:
        """初始化链接解析器。

        参数:
            http_client: 用于跟随短链重定向的 HttpClient 实例。
        """
        self._http_client = http_client

    def extract_url(self, text: str) -> str | None:
        """从任意文本中提取第一个抖音链接 URL。

        支持识别的输入格式：
            - 抖音短链：``https://v.douyin.com/xxxxx/``
            - 抖音长链（视频）：``https://www.douyin.com/video/{aweme_id}``
            - 抖音长链（直播回放）：``https://www.douyin.com/vsdetail/{aweme_id}``
            - 抖音长链（合集）：``https://www.douyin.com/mix/{aweme_id}``
            - 抖音长链（主页）：``https://www.douyin.com/user/{sec_user_id}``
            - 分享口令（含中文描述 + 短链）
            - 多链接文本（取第一个）

        参数:
            text: 原始文本。

        返回:
            提取到的 URL 字符串；未找到返回 None。
        """
        if not text:
            return None
        for match in _URL_PATTERN.finditer(text):
            url = match.group(0)
            # 去除末尾可能粘连的标点（如右括号、句号）
            url = url.rstrip(".,;:)]}。，；：）】》")
            if self._is_douyin_url(url):
                return url
        return None

    def extract_short_urls(self, text: str) -> list[str]:
        """从文本中提取所有抖音短链（``https://v.douyin.com/xxx/``）。

        v0.1.5：保守匹配，仅匹配 ``v.douyin.com`` 短链格式，宁可漏匹配也
        不要错误匹配描述文字（用户反馈 #1）。用于多行分享文本批量提取短链。

        参数:
            text: 原始文本（可能含多行、描述文字、短链）。

        返回:
            提取到的短链列表（保持出现顺序）；无匹配返回空列表。
        """
        if not text:
            return []
        return _SHORT_URL_PATTERN.findall(text)

    @staticmethod
    def _is_douyin_url(url: str) -> bool:
        """判断 URL 是否属于抖音合法域名。

        参数:
            url: 待判断的 URL 字符串。

        返回:
            属于抖音域名返回 True，否则 False。
        """
        url_lower = url.lower()
        # 提取 host 部分：https://host/path → host
        host_match = re.match(r"https?://([^/]+)/?", url_lower)
        if not host_match:
            return False
        host = host_match.group(1).split(":")[0]
        return host in _DOUYIN_DOMAINS

    def identify_type(self, url: str) -> LinkType:
        """根据 URL 路径与查询参数识别链接类型。

        识别规则（按优先级）:
            1. 路径含 ``/user/`` 或查询参数含 ``sec_user_id`` → ``'user_home'``
            2. 路径含 ``/video/`` 或查询参数含 ``aweme_id`` → ``'video'``
               （image_set / long_video 的最终判定依赖 v0.0.4 VideoParser 调用
               detail 接口后的结果，URLParser 统一归为 ``'video'``）
            3. 路径含 ``/vsdetail/`` → ``'video'``（直播回放/录播视频）
            4. 路径含 ``/mix/`` 或 ``/collection/`` → ``'video'``（合集/合辑页面）
            5. 路径含 ``/share/slides/`` → ``'video'``（图文分享/幻灯片）
            6. 其他 → 抛 ``InvalidURLFormatError``

        参数:
            url: 已规范化的 URL（短链需先 follow_redirect 拿到最终 URL）。

        返回:
            LinkType 类型字符串。

        异常:
            InvalidURLFormatError: 无法从 URL 识别类型。
        """
        try:
            parsed = urlparse(url)
        except ValueError as e:
            raise InvalidURLFormatError(f"URL 格式无效: {url}") from e
        path = parsed.path or ""
        query = parse_qs(parsed.query or "")
        # 规则 1：用户主页
        if "/user/" in path or "sec_user_id" in query:
            return "user_home"
        # 规则 2：视频/图文/长视频（统一归 video）
        if "/video/" in path or "aweme_id" in query:
            return "video"
        # 规则 3：直播回放/录播视频
        if "/vsdetail/" in path:
            return "video"
        # 规则 4：合集/合辑页面
        if "/mix/" in path or "/collection/" in path:
            return "video"
        # 规则 5：图文分享/幻灯片（iesdouyin.com/share/slides/）
        if "/share/slides/" in path:
            return "video"
        # 规则 6：无法识别
        raise InvalidURLFormatError(f"无法识别的抖音链接类型: {url}")

    @staticmethod
    def extract_aweme_id(url: str) -> str | None:
        """从 URL 中提取 aweme_id。

        支持两种格式（查询参数优先）：
            - 查询参数：``?aweme_id={aweme_id}``
            - 路径形式：``/video/{aweme_id}`` 或 ``/share/video/{aweme_id}``
            - 路径形式：``/vsdetail/{aweme_id}``（直播回放）
            - 路径形式：``/mix/{aweme_id}`` 或 ``/collection/{aweme_id}``（合集）
            - 路径形式：``/share/slides/{aweme_id}``（图文分享）

        参数:
            url: 已规范化的 URL。

        返回:
            aweme_id 字符串；未找到返回 None。
        """
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        # 查询参数形式优先
        query = parse_qs(parsed.query or "")
        if "aweme_id" in query and query["aweme_id"]:
            return query["aweme_id"][0]
        # 路径形式：取 /video/ /vsdetail/ /mix/ /collection/ /share/slides/ 后的段
        path_parts = (parsed.path or "").split("/")
        for i, part in enumerate(path_parts):
            if (
                part in ("video", "vsdetail", "mix", "collection", "slides")
                and i + 1 < len(path_parts)
                and path_parts[i + 1]
            ):
                return path_parts[i + 1]
        return None

    @staticmethod
    def extract_sec_user_id(url: str) -> str | None:
        """从 URL 中提取 sec_user_id。

        支持两种格式（查询参数优先）：
            - 查询参数：``?sec_user_id={sec_user_id}``
            - 路径形式：``/user/{sec_user_id}``（仅当 /user/ 后紧跟单段时）

        参数:
            url: 已规范化的 URL。

        返回:
            sec_user_id 字符串；未找到返回 None。
        """
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        # 查询参数形式优先
        query = parse_qs(parsed.query or "")
        if "sec_user_id" in query and query["sec_user_id"]:
            return query["sec_user_id"][0]
        # 路径形式：/user/{sec_user_id}，要求 /user/ 后紧跟且仅一段
        # 避免误匹配 /user/profile/other 这类 API 路径
        path_parts = [p for p in (parsed.path or "").split("/") if p]
        for i, part in enumerate(path_parts):
            if part == "user" and i + 1 < len(path_parts):
                next_part = path_parts[i + 1]
                # sec_user_id 通常以 MS4w 开头且较长，API 子路径（profile/other）较短
                # 此处保守判断：/user/ 后必须是最后一段（无更多子路径）
                if i + 2 == len(path_parts) and next_part:
                    return next_part
        return None

    async def follow_redirect(self, short_url: str) -> str:
        """跟随 v.douyin.com 短链重定向，返回最终落地 URL。

        不带 Cookie 与签名（短链重定向不需要），调用 HttpClient.get
        （use_cookie_pool=False）获取响应，从 ``httpx.Response.url`` 取最终 URL。

        参数:
            short_url: 短链 URL（如 ``https://v.douyin.com/AbCd123/``）。

        返回:
            最终落地 URL 字符串。

        异常:
            NetworkError: 重定向失败/超时。
        """
        # HttpClient.get 已设置 follow_redirects=False，但短链重定向需要跟随
        # 此处通过 use_cookie_pool=False 调用，让 HttpClient 发起请求
        # 由于 follow_redirects=False，response.url 即为最终 URL（短链本身不会重定向）
        # 实际上 v.douyin.com 短链返回 302 + Location 头，我们需要手动解析
        response = await self._http_client.get(
            short_url,
            use_cookie_pool=False,
        )
        # httpx.Response.url 在 follow_redirects=False 时为请求 URL 本身
        # 检查 Location 头获取重定向目标
        location = response.headers.get("location")
        if location:
            return location
        # 无 Location 头，返回响应 URL（已是最终 URL）
        return str(response.url)

    async def parse(self, text: str) -> ParsedURL:
        """解析用户粘贴的链接文本。

        流程：
            1. ``extract_url`` 提取 URL；若返回 None，抛 ``InvalidURLFormatError``
            2. 若为短链（``v.douyin.com``），调用 ``follow_redirect`` 获取最终 URL
            3. ``identify_type`` 识别类型
            4. 根据类型从 URL 提取 ``aweme_id`` 或 ``sec_user_id``
            5. 构造并返回 ``ParsedURL``

        支持的长链路径类型：
            - ``/video/{aweme_id}`` — 普通视频
            - ``/vsdetail/{aweme_id}`` — 直播回放/录播视频（可能需灯牌等级）
            - ``/mix/{aweme_id}`` 或 ``/collection/{aweme_id}`` — 合集/合辑页面
               （目前仅解析合集页的首个视频 aweme_id，完整合集解析需额外 API 调用）
            - ``/user/{sec_user_id}`` — 用户主页

        参数:
            text: 用户粘贴的原始文本，可能含分享口令、短链、长链。

        返回:
            ParsedURL 数据结构。

        异常:
            InvalidURLFormatError: 文本中无可识别的抖音链接。
            NetworkError: 短链重定向失败。
        """
        url = self.extract_url(text)
        if url is None:
            raise InvalidURLFormatError(f"文本中未找到抖音链接: {text!r}")

        # 短链需跟随重定向
        if "v.douyin.com" in url.lower():
            final_url = await self.follow_redirect(url)
        else:
            final_url = url

        link_type = self.identify_type(final_url)
        if link_type == "user_home":
            aweme_id = None
            sec_user_id = self.extract_sec_user_id(final_url)
        else:
            aweme_id = self.extract_aweme_id(final_url)
            sec_user_id = None

        return ParsedURL(
            type=link_type,
            url=final_url,
            aweme_id=aweme_id,
            sec_user_id=sec_user_id,
            original_text=text,
        )
