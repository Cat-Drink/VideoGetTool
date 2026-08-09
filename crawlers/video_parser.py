"""视频解析器模块。

根据 ``aweme_id`` 调用抖音 ``aweme/v1/web/aweme/detail`` 接口，
解析出无水印直链与完整元数据，区分 video / image_set / long_video 三种类型。

接口契约见 ``docs/structure/05-接口设计文档.md`` 第 3.3 节；
实现规范见 ``docs/plans/v0.0.4-视频解析与主页抓取.md`` 第 3 节。

设计要点:
    - 通过依赖注入接收 HttpClient 与 Signer，不持有网络连接
    - HTTP 层风控（461/412/429/验证 HTML/网络异常）已由 HttpClient 统一处理
    - 本模块仅处理 HTTP 200 + ``status_code != 0`` 业务错误与 JSON 字段提取
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from app.logger import get_logger
from crawlers import api_spec
from crawlers.exceptions import VideoNotFoundError
from downloader.constants import LONG_VIDEO_DURATION_THRESHOLD

if TYPE_CHECKING:
    from crawlers.http_client import HttpClient
    from crawlers.signer import Signer

logger = get_logger(__name__)


# === 类型别名 ===

# 抖音作品类型（与计划文档 11.2 节一致，供 UserHomeCrawler 复用）
VideoType = Literal["video", "image_set", "long_video"]


# 长视频时长阈值（毫秒），由 downloader.constants.LONG_VIDEO_DURATION_THRESHOLD（秒）换算
# v0.1.3：长视频定义从 > 60 秒改为 ≥ 30 分钟（用户反馈 #12）
_LONG_VIDEO_DURATION_MS: int = LONG_VIDEO_DURATION_THRESHOLD * 1000


# === 数据结构 ===


@dataclass(frozen=True)
class VideoInfo:
    """视频/图集解析结果。

    类型与字段对应关系:
        - ``type='video'`` 或 ``'long_video'`` 时：
          ``no_watermark_url`` 必填、``image_urls`` 为空列表、``duration`` 非 None
        - ``type='image_set'`` 时：
          ``image_urls`` 必填（至少 1 条）、``no_watermark_url`` 为 None、
          ``duration`` 为 None

    字段来源映射见计划文档 3.2 节字段清单。
    """

    aweme_id: str
    type: VideoType
    title: str
    author: str
    author_sec_id: str
    duration: str | None
    cover_url: str
    no_watermark_url: str | None
    image_urls: list[str]
    publish_time: str | None
    like_count: int
    comment_count: int
    share_count: int
    collect_count: int
    tags: list[str]
    raw_json: dict


# === VideoParser 类（Step 3-4 补充实现） ===


class VideoParser:
    """视频解析器。

    依赖 HttpClient（注入签名与 Cookie）调用抖音 detail 接口，
    从响应中提取无水印直链与元数据。

    异常处理:
        HTTP 层风控异常（CookieInvalidError / RateLimitedError /
        VerifyRequiredError / NetworkError）由 HttpClient 直接抛出；
        本类仅处理:
            - ``status_code != 0`` 业务错误 → VideoNotFoundError
            - JSON 结构不符合预期 → VideoNotFoundError
    """

    def __init__(self, http_client: HttpClient, signer: Signer) -> None:
        """初始化视频解析器。

        参数:
            http_client: HttpClient 实例（提供签名 + Cookie 注入的请求能力）。
            signer: Signer 实例（保留注入以便未来扩展自定义请求参数）。
        """
        self._http_client = http_client
        self._signer = signer

    # === 私有辅助方法 ===

    @staticmethod
    def _detect_video_type(detail: dict) -> VideoType:
        """根据响应数据判断作品类型。

        判断顺序（先命中先返回，见计划文档 3.5 节）:
            1. ``images`` 字段非空（列表长度 > 0） → ``'image_set'``
            2. ``video.duration`` ≥ 1800000 毫秒（≥ 30 分钟） → ``'long_video'``
            3. 其他情况 → ``'video'``

        v0.1.3：长视频阈值从 ``> 60000`` 毫秒（60 秒）改为
        ``>= LONG_VIDEO_DURATION_THRESHOLD * 1000`` 毫秒（30 分钟），
        阈值常量定义在 ``downloader/constants.py``。

        参数:
            detail: ``aweme_detail`` 节点。

        返回:
            ``'video'`` / ``'image_set'`` / ``'long_video'``。
        """
        images = detail.get("images")
        if isinstance(images, list) and len(images) > 0:
            return "image_set"
        duration = detail.get("video", {}).get("duration", 0) or 0
        if duration >= _LONG_VIDEO_DURATION_MS:
            return "long_video"
        return "video"

    @staticmethod
    def _format_duration(ms: int) -> str:
        """毫秒转展示文本。

        规则:
            - < 60 秒 → ``'Xs'``（如 ``'15s'``）
            - >= 60 秒 → ``'MM:SS'``（如 ``'12:30'``），小时以上仍按 MM:SS 展示
              （如 1 小时 30 分 15 秒 → ``'90:15'``）

        参数:
            ms: 视频时长（毫秒）。

        返回:
            展示文本。
        """
        total_seconds = ms // 1000
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _extract_tags(detail: dict) -> list[str]:
        """从 ``text_extra`` 提取标签名列表。

        参数:
            detail: ``aweme_detail`` 节点。

        返回:
            标签名列表（无标签时为空列表）。
        """
        text_extra = detail.get("text_extra")
        if not isinstance(text_extra, list):
            return []
        tags: list[str] = []
        for item in text_extra:
            if not isinstance(item, dict):
                continue
            name = item.get("hashtag_name")
            if isinstance(name, str) and name:
                tags.append(name)
        return tags

    @staticmethod
    def _extract_no_watermark_url(detail: dict) -> str | None:
        """提取视频无水印直链。

        路径（见计划文档 3.4.1 节）:
            - 主路径: ``video.play_addr.url_list[0]``
            - 回退: 若 URL 含 ``playwm`` 子串，替换为 ``play`` 得无水印直链

        参数:
            detail: ``aweme_detail`` 节点。

        返回:
            无水印直链；列表为空时返回 None。
        """
        url_list = detail.get("video", {}).get("play_addr", {}).get("url_list")
        if not isinstance(url_list, list) or not url_list:
            return None
        url = url_list[0]
        if not isinstance(url, str) or not url:
            return None
        if "playwm" in url:
            url = url.replace("playwm", "play")
        return url

    @staticmethod
    def _extract_image_urls(detail: dict) -> list[str]:
        """提取图集原图直链列表。

        路径（见计划文档 3.4.2 节）: 遍历 ``images`` 数组，每项取 ``url_list[0]``。

        参数:
            detail: ``aweme_detail`` 节点。

        返回:
            图片 URL 列表（无图集时为空列表）。
        """
        images = detail.get("images")
        if not isinstance(images, list):
            return []
        urls: list[str] = []
        for img in images:
            if not isinstance(img, dict):
                continue
            url_list = img.get("url_list")
            if not isinstance(url_list, list) or not url_list:
                continue
            url = url_list[0]
            if isinstance(url, str) and url:
                urls.append(url)
        return urls

    @staticmethod
    def _build_detail_params(aweme_id: str) -> dict:
        """构造 detail 接口业务参数。

        参数:
            aweme_id: 抖音作品 ID。

        返回:
            含 ``aweme_id`` 与所有固定参数的字典。
        """
        return {"aweme_id": aweme_id, **api_spec.COMMON_FIXED_PARAMS}

    @staticmethod
    def _format_publish_time(create_time: int | None) -> str | None:
        """Unix 秒转 ISO8601 字符串。

        参数:
            create_time: ``aweme_detail.create_time``（Unix 秒）；None 或 ≤ 0 返回 None。

        返回:
            ``'YYYY-MM-DDTHH:MM:SSZ'`` 格式字符串；无效输入返回 None。
        """
        if not create_time or create_time <= 0:
            return None
        return datetime.fromtimestamp(create_time, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _extract_cover_url(detail: dict) -> str:
        """提取封面图 URL。

        路径: ``video.cover.url_list[0]``。缺失时返回空字符串。
        """
        url_list = detail.get("video", {}).get("cover", {}).get("url_list")
        if isinstance(url_list, list) and url_list and isinstance(url_list[0], str):
            return url_list[0]
        return ""

    @staticmethod
    def _extract_statistics(detail: dict) -> tuple[int, int, int, int]:
        """提取统计字段。

        路径: ``statistics.{digg_count, comment_count, share_count, collect_count}``。
        缺失或类型异常的字段返回 0。
        """
        stats = detail.get("statistics")
        if not isinstance(stats, dict):
            return (0, 0, 0, 0)

        def _safe_int(key: str) -> int:
            val = stats.get(key)
            if isinstance(val, int):
                return val
            if isinstance(val, str) and val.isdigit():
                return int(val)
            return 0

        return (
            _safe_int("digg_count"),
            _safe_int("comment_count"),
            _safe_int("share_count"),
            _safe_int("collect_count"),
        )

    @classmethod
    def _build_video_info(cls, detail: dict) -> VideoInfo:
        """从 ``aweme_detail`` 节点构造 VideoInfo。

        参数:
            detail: ``aweme_detail`` 节点（已确认非空）。

        返回:
            VideoInfo 实例。
        """
        video_type = cls._detect_video_type(detail)
        if video_type == "image_set":
            no_watermark_url = cls._extract_no_watermark_url(detail)
            image_urls = cls._extract_image_urls(detail)
            duration: str | None = None
        else:
            no_watermark_url = cls._extract_no_watermark_url(detail)
            image_urls = []
            raw_duration = detail.get("video", {}).get("duration")
            duration = (
                cls._format_duration(raw_duration)
                if isinstance(raw_duration, int) and raw_duration > 0
                else None
            )

        like_count, comment_count, share_count, collect_count = cls._extract_statistics(detail)
        author = detail.get("author") or {}
        return VideoInfo(
            aweme_id=str(detail.get("aweme_id") or ""),
            type=video_type,
            title=str(detail.get("desc") or ""),
            author=str(author.get("nickname") or ""),
            author_sec_id=str(author.get("sec_uid") or ""),
            duration=duration,
            cover_url=cls._extract_cover_url(detail),
            no_watermark_url=no_watermark_url,
            image_urls=image_urls,
            publish_time=cls._format_publish_time(detail.get("create_time")),
            like_count=like_count,
            comment_count=comment_count,
            share_count=share_count,
            collect_count=collect_count,
            tags=cls._extract_tags(detail),
            raw_json=detail,
        )

    # === 主流程 ===

    async def parse_video(self, aweme_id: str, cookie: str) -> VideoInfo:
        """解析单个作品信息。

        流程（见计划文档 3.6 节）:
            1. 构造 detail 接口业务参数
            2. 调用 HttpClient.get（签名/Cookie/风控由 HttpClient 处理）
            3. 解析 JSON、检查 ``status_code`` 与 ``aweme_detail``
            4. 构造 VideoInfo 并返回

        参数:
            aweme_id: 抖音作品 ID。
            cookie: 调用本次请求所用的 Cookie 字符串。

        返回:
            VideoInfo 数据结构。

        异常:
            VideoNotFoundError: 作品已删除/私密、``aweme_detail`` 缺失或 status_code 非 0。
            CookieInvalidError: Cookie 失效（由 HttpClient 抛出）。
            RateLimitedError: 触发限流（由 HttpClient 抛出）。
            VerifyRequiredError: 触发安全验证（由 HttpClient 抛出）。
            NetworkError: 网络异常或响应非 JSON（由 HttpClient 抛出）。
        """
        params = self._build_detail_params(aweme_id)
        logger.info("解析作品 aweme_id=%s", aweme_id)
        response = await self._http_client.get(
            api_spec.AWEME_DETAIL_URL,
            params=params,
            use_cookie_pool=False,
            cookie=cookie,
        )

        # HTTP 200 后才到这里：JSON 解析由 httpx 自动完成，失败抛 NetworkError
        try:
            payload = response.json()
        except ValueError as e:
            logger.error("响应 JSON 解析失败: aweme_id=%s error=%s", aweme_id, e)
            raise VideoNotFoundError(f"作品详情响应非 JSON: {e}") from e

        status_code = payload.get("status_code")
        if status_code != 0:
            status_msg = payload.get("status_msg") or "未知错误"
            logger.warning(
                "作品详情业务错误: aweme_id=%s status_code=%s msg=%s",
                aweme_id,
                status_code,
                status_msg,
            )
            raise VideoNotFoundError(f"作品已删除或设为私密（{status_code}: {status_msg}）")

        detail = payload.get("aweme_detail")
        if not isinstance(detail, dict):
            logger.warning("aweme_detail 缺失或非 dict: aweme_id=%s", aweme_id)
            raise VideoNotFoundError("作品详情解析失败：aweme_detail 缺失")

        return self._build_video_info(detail)
