"""用户主页抓取器模块。

根据 ``sec_user_id`` 分页拉取抖音 ``aweme/v1/web/aweme/post`` 接口，
按类型/数量/时间段过滤后异步产出 ``PostItem`` 流。

接口契约见 ``docs/structure/05-接口设计文档.md`` 第 3.4 节；
实现规范见 ``docs/plans/v0.0.4-视频解析与主页抓取.md`` 第 4 节。

设计要点:
    - 通过依赖注入接收 HttpClient 与 Signer，不持有网络连接
    - HTTP 层风控（461/412/429/验证 HTML/网络异常）已由 HttpClient 统一处理
    - 本模块仅处理 HTTP 200 + ``status_code != 0`` 业务错误与分页/过滤逻辑
    - 字段命名沿用计划文档 4.2.1 节（max_count / start_date / end_date），
      与接口文档 3.4 节的 count_limit / date_from / date_to 等价
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from app.logger import get_logger
from crawlers import api_spec
from crawlers.exceptions import UserNotFoundError
from downloader.constants import LONG_VIDEO_DURATION_THRESHOLD

if TYPE_CHECKING:
    from crawlers.http_client import HttpClient
    from crawlers.signer import Signer

logger = get_logger(__name__)


def _normalize_cover_url(url: str) -> str:
    """归一化封面/图片地址为 HTTPS。

    抖音接口返回的封面 url_list 常为 http:// 地址；在 Tauri 打包后的
    WebView 中 http 子资源会被当作混合内容拦截，导致封面不显示。
    https 变体经实测可用（同一资源），因此统一替换为 https。
    """
    if url and url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


# === 类型别名 ===

# 主页抓取类型过滤（与计划文档 11.2 节一致）
HomeFilterType = Literal["all", "video", "image_set", "long_video"]


# 长视频时长阈值（毫秒），由 downloader.constants.LONG_VIDEO_DURATION_THRESHOLD（秒）换算
# v0.1.3：长视频定义从 > 60 秒改为 ≥ 30 分钟（用户反馈 #12）
_LONG_VIDEO_DURATION_MS: int = LONG_VIDEO_DURATION_THRESHOLD * 1000


# === 数据结构 ===


@dataclass(frozen=True)
class HomeFilters:
    """主页抓取过滤条件。

    字段命名沿用 v0.0.4 计划文档 4.2.1 节，与接口文档 3.4 节的
    ``count_limit`` / ``date_from`` / ``date_to`` 等价：
        - ``max_count`` ≡ ``count_limit``：数量上限，``0`` 表示不限
        - ``start_date`` ≡ ``date_from``：起始日期 ``YYYY-MM-DD``（含），``None`` 不限
        - ``end_date`` ≡ ``date_to``：结束日期 ``YYYY-MM-DD``（含当日 23:59:59），``None`` 不限
    """

    type_filter: HomeFilterType = "all"
    max_count: int = 0
    start_date: str | None = None
    end_date: str | None = None


@dataclass(frozen=True)
class PostItem:
    """主页作品列表项（轻量信息，供 UI 勾选）。

    与 VideoInfo 不同，PostItem 不含无水印直链——直链在用户勾选后
    由 VideoParser 二次调用 detail 接口获取（见计划文档 4.2.2 节）。
    """

    aweme_id: str
    title: str
    author: str
    author_sec_id: str
    cover_url: str
    type: str
    create_time: str
    duration: str | None
    image_count: int | None


# === UserHomeCrawler 类（Step 7-8 补充实现） ===


class UserHomeCrawler:
    """用户主页抓取器。

    调用 aweme/v1/web/aweme/post 接口分页拉取，使用 max_cursor 翻页。

    异常处理:
        HTTP 层风控异常（CookieInvalidError / RateLimitedError /
        VerifyRequiredError / NetworkError）由 HttpClient 直接抛出；
        本类仅处理:
            - ``status_code != 0`` 业务错误 → UserNotFoundError
            - ``aweme_list`` 字段缺失 → 视为空列表，正常结束迭代
    """

    def __init__(self, http_client: HttpClient, signer: Signer) -> None:
        """初始化主页抓取器。

        参数:
            http_client: HttpClient 实例（提供签名 + Cookie 注入的请求能力）。
            signer: Signer 实例（保留注入以便未来扩展）。
        """
        self._http_client = http_client
        self._signer = signer

    # === 私有辅助方法 ===

    @staticmethod
    def _build_post_params(sec_user_id: str, max_cursor: int) -> dict:
        """构造 post 接口业务参数。

        参数:
            sec_user_id: 用户主页 sec_user_id。
            max_cursor: 分页游标（首次为 0，后续取上一页响应的 max_cursor）。

        返回:
            含 sec_user_id/max_cursor/count 与所有固定参数的字典。
        """
        return {
            "sec_user_id": sec_user_id,
            "max_cursor": str(max_cursor),
            "count": str(api_spec.POST_PAGE_SIZE),
            **api_spec.COMMON_FIXED_PARAMS,
        }

    @staticmethod
    def _detect_type(aweme: dict) -> str:
        """判断单条 aweme 的类型（同 VideoParser._detect_video_type 规则）。

        判断顺序:
            1. ``images`` 非空 → ``'image_set'``
            2. ``video.duration`` ≥ 1800000 毫秒（≥ 30 分钟） → ``'long_video'``
            3. 其他 → ``'video'``

        v0.1.3：长视频阈值从 ``> 60000`` 毫秒改为
        ``>= LONG_VIDEO_DURATION_THRESHOLD * 1000`` 毫秒，
        阈值常量定义在 ``downloader/constants.py``。
        """
        images = aweme.get("images")
        if isinstance(images, list) and len(images) > 0:
            return "image_set"
        duration = aweme.get("video", {}).get("duration", 0) or 0
        if duration >= _LONG_VIDEO_DURATION_MS:
            return "long_video"
        return "video"

    @staticmethod
    def _format_create_time(create_time: int | None) -> str:
        """Unix 秒转 ISO8601 字符串。

        参数:
            create_time: ``aweme.create_time``（Unix 秒）。

        返回:
            ``'YYYY-MM-DDTHH:MM:SSZ'`` 格式字符串；无效输入（None/≤0）返回空字符串。
        """
        if not create_time or create_time <= 0:
            return ""
        return datetime.fromtimestamp(create_time, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _format_duration(ms: int | None) -> str | None:
        """毫秒转展示文本（与 VideoParser._format_duration 一致）。

        参数:
            ms: 视频时长（毫秒）；None 或 ≤ 0 返回 None。

        返回:
            展示文本或 None。
        """
        if not ms or ms <= 0:
            return None
        total_seconds = ms // 1000
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    @classmethod
    def _build_post_item(cls, aweme: dict) -> PostItem:
        """从单条 aweme 节点构造 PostItem。

        参数:
            aweme: ``aweme_list[i]`` 节点。

        返回:
            PostItem 实例。
        """
        item_type = cls._detect_type(aweme)
        if item_type == "image_set":
            duration: str | None = None
            images = aweme.get("images")
            image_count = len(images) if isinstance(images, list) else 0
        else:
            raw_duration = aweme.get("video", {}).get("duration")
            duration = cls._format_duration(raw_duration if isinstance(raw_duration, int) else None)
            image_count = None

        author = aweme.get("author") or {}
        cover_url_list = aweme.get("video", {}).get("cover", {}).get("url_list")
        cover_url = ""
        if (
            isinstance(cover_url_list, list)
            and cover_url_list
            and isinstance(cover_url_list[0], str)
        ):
            cover_url = _normalize_cover_url(cover_url_list[0])
        return PostItem(
            aweme_id=str(aweme.get("aweme_id") or ""),
            title=str(aweme.get("desc") or ""),
            author=str(author.get("nickname") or ""),
            author_sec_id=str(author.get("sec_uid") or ""),
            cover_url=cover_url,
            type=item_type,
            create_time=cls._format_create_time(aweme.get("create_time")),
            duration=duration,
            image_count=image_count,
        )

    @staticmethod
    def _date_to_timestamp(date_str: str | None, end_of_day: bool = False) -> float | None:
        """``YYYY-MM-DD`` 字符串转 Unix 时间戳。

        参数:
            date_str: ``'2026-01-01'`` 格式；``None`` 返回 ``None``。
            end_of_day: ``False`` 取当日 00:00:00，``True`` 取当日 23:59:59。

        返回:
            Unix 时间戳（秒）；解析失败返回 ``None``。
        """
        if date_str is None:
            return None
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            logger.warning("日期格式无法解析: %s", date_str)
            return None
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.timestamp()

    @staticmethod
    def _parse_iso8601_to_timestamp(iso_str: str) -> float | None:
        """ISO8601 字符串转 Unix 时间戳。

        参数:
            iso_str: ``'2026-01-01T00:00:00Z'`` 格式。

        返回:
            Unix 时间戳（秒）；解析失败返回 ``None``。
        """
        try:
            return datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
        except (ValueError, TypeError):
            logger.warning("ISO8601 时间无法解析: %s", iso_str)
            return None

    @classmethod
    def _match_filters(cls, item: PostItem, filters: HomeFilters) -> bool:
        """应用过滤逻辑（见计划文档 4.4 节）。

        多个条件为 AND 关系，全部满足才返回 True。

        参数:
            item: 待判断的 PostItem。
            filters: 过滤条件。

        返回:
            符合全部过滤条件返回 True，否则 False。
        """
        # 类型过滤
        if filters.type_filter != "all" and item.type != filters.type_filter:
            return False

        # 日期过滤（仅当 create_time 有效时应用；空 create_time 视为不匹配任何日期范围）
        if filters.start_date is not None or filters.end_date is not None:
            if not item.create_time:
                return False
            item_ts = cls._parse_iso8601_to_timestamp(item.create_time)
            if item_ts is None:
                return False
            if filters.start_date is not None:
                start_ts = cls._date_to_timestamp(filters.start_date, end_of_day=False)
                if start_ts is not None and item_ts < start_ts:
                    return False
            if filters.end_date is not None:
                end_ts = cls._date_to_timestamp(filters.end_date, end_of_day=True)
                if end_ts is not None and item_ts > end_ts:
                    return False

        return True

    # === 主流程 ===

    async def fetch_user_posts(
        self,
        sec_user_id: str,
        filters: HomeFilters,
        cookie: str,
        progress_callback: Callable[[int], None] | None = None,
    ) -> AsyncIterator[PostItem]:
        """异步迭代产出符合过滤条件的作品。

        流程（见计划文档 4.3 节）:
            1. 维护分页游标 ``max_cursor``，初始为 0
            2. 循环调用 post 接口
            3. 每页解析 ``aweme_list``，逐条构造 PostItem
            4. 对每个 PostItem 应用过滤逻辑，符合条件则 yield
            5. 每拉取一页后调用 ``progress_callback(已抓取总数)``
            6. 根据 ``has_more`` / ``max_count`` / 游标是否变化决定是否继续

        参数:
            sec_user_id: 用户主页 sec_user_id。
            filters: 过滤条件（类型/数量/时间段）。
            cookie: 调用本次请求所用的 Cookie 字符串。
            progress_callback: 进度回调，传入"已抓取总数"（含未通过过滤的）；
                为 None 时跳过。回调异常仅记录日志，不中断抓取。

        返回:
            异步迭代器，逐个 yield PostItem。

        异常:
            UserNotFoundError: 用户主页不存在或不可见（status_code != 0）。
            CookieInvalidError / RateLimitedError / VerifyRequiredError / NetworkError:
                由 HttpClient 抛出。
        """
        max_cursor = 0
        yielded_count = 0
        fetched_count = 0
        logger.info("开始抓取主页 sec_user_id=%s filters=%s", sec_user_id, filters)

        while True:
            params = self._build_post_params(sec_user_id, max_cursor)
            response = await self._http_client.get(
                api_spec.AWEME_POST_URL,
                params=params,
                use_cookie_pool=False,
                cookie=cookie,
            )

            # HTTP 200 后才到这里：解析 JSON
            try:
                payload = response.json()
            except ValueError as e:
                logger.error("主页响应 JSON 解析失败: sec_user_id=%s error=%s", sec_user_id, e)
                raise UserNotFoundError(f"主页响应非 JSON: {e}") from e

            status_code = payload.get("status_code")
            # 抖音 API 有时返回字符串，做防御性 int 转换
            if int(status_code or 0) != 0:
                status_msg = payload.get("status_msg") or "未知错误"
                logger.warning(
                    "主页业务错误: sec_user_id=%s status_code=%s msg=%s",
                    sec_user_id,
                    status_code,
                    status_msg,
                )
                raise UserNotFoundError(f"用户主页不存在或不可见（{status_code}: {status_msg}）")

            aweme_list = payload.get("aweme_list")
            if not isinstance(aweme_list, list):
                aweme_list = []
            has_more = payload.get("has_more")
            next_cursor = payload.get("max_cursor")

            for aweme in aweme_list:
                if not isinstance(aweme, dict):
                    continue
                fetched_count += 1
                item = self._build_post_item(aweme)
                if self._match_filters(item, filters):
                    yield item
                    yielded_count += 1
                    if filters.max_count > 0 and yielded_count >= filters.max_count:
                        # 达到数量上限，提前结束
                        self._invoke_progress(progress_callback, fetched_count)
                        return

            # 每页拉取完成后通知进度
            self._invoke_progress(progress_callback, fetched_count)

            # 终止条件 1：无更多作品
            # 抖音接口有时返回字符串 "1"/"0"，做防御性 int 转换
            if int(has_more or 0) != 1:
                return
            # 终止条件 2：游标无效（None 或非数字）
            try:
                next_cursor_val = int(next_cursor)
            except (ValueError, TypeError):
                logger.warning(
                    "主页游标无效，终止抓取: sec_user_id=%s cursor=%r",
                    sec_user_id,
                    next_cursor,
                )
                return
            # 终止条件 3：游标未变化，防止死循环；比较归一化后的数值，
            # 兼容接口返回字符串 "0"/"100" 的情况。
            if next_cursor_val == max_cursor:
                logger.warning(
                    "主页游标未变化，终止抓取: sec_user_id=%s cursor=%s",
                    sec_user_id,
                    max_cursor,
                )
                return
            if next_cursor_val < 0:
                logger.warning(
                    "主页游标为负，终止抓取: sec_user_id=%s cursor=%s",
                    sec_user_id,
                    next_cursor_val,
                )
                return
            max_cursor = next_cursor_val
            # 审计 M11/D3：翻页限速，压低短时请求脉冲，降低 461/412 风控概率
            from crawlers.http_client import pagination_throttle

            await pagination_throttle()

    @staticmethod
    def _invoke_progress(
        progress_callback: Callable[[int], None] | None,
        fetched_count: int,
    ) -> None:
        """安全调用进度回调，回调异常仅记录日志不中断抓取。

        参数:
            progress_callback: 回调函数；None 时直接返回。
            fetched_count: 已抓取总数（含未通过过滤的）。
        """
        if progress_callback is None:
            return
        try:
            progress_callback(fetched_count)
        except Exception as e:
            logger.warning("进度回调异常（已忽略）: %s", e)
