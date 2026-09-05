"""HTTP 客户端模块。

封装 ``curl_cffi.requests.AsyncSession`` 单例，统一注入签名、Cookie、Headers，
提供异步 GET 请求入口与 Cookie 池管理（轮询取用 / 失败上报 / 全池失效检测）。

为什么用 curl_cffi：
    抖音 Janus 风控通过 TLS 指纹（JA3/JA4）识别非浏览器 HTTP 客户端，
    对 ``aweme/v1/web/*`` 接口返回 HTTP 200 + 空 body 软封禁。curl_cffi 的
    ``impersonate="chrome"`` 可伪造与真实 Chrome 一致的 TLS/HTTP2 指纹，
    绕过该检测（详见 ``docs/hotfix/root-cause.md``）。

接口签名与 ``docs/structure/05-接口设计文档.md`` 第 3.5 节保持一致。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from curl_cffi.requests import AsyncSession
from curl_cffi.requests import Response as CurlResponse
from curl_cffi.requests.exceptions import RequestException as CurlRequestsError

from app.logger import get_logger
from app.models import Cookie, now_iso
from crawlers.exceptions import (
    CookieInvalidError,
    NetworkError,
    RateLimitedError,
    VerifyRequiredError,
)
from crawlers.signer import DEFAULT_USER_AGENT

if TYPE_CHECKING:
    from app.repositories import CookieRepository
    from crawlers.signer import Signer

logger = get_logger(__name__)

# === 类型别名 ===

CookieStatus = Literal["valid", "invalid", "untested"]

# === 模块级常量 ===

# 默认请求头（与签名算法使用的 UA 保持一致，避免 UA 不匹配导致签名失效）
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 风控响应 HTTP 状态码集合（461/412 统一视为 Cookie 失效/风控）
RISK_STATUS_CODES: frozenset[int] = frozenset({461, 412})

# 滑动验证 HTML 特征字符串（任一命中即判定为验证页面）
VERIFY_HTML_MARKERS: tuple[str, ...] = (
    "captcha_verify",
    "verify_type",
    "verifydouyin",
    "slide_verify",
)

# Cookie 连续失败上限：达到此值后置 status='invalid'
MAX_FAIL_COUNT: int = 3

# 最大同时请求数（并发信号量），避免脉冲式请求造成 burst
_MAX_CONCURRENT_REQUESTS: int = 3

# 限流重试参数：指数退避，最大重试次数
_RETRY_MAX_ATTEMPTS: int = 3
_RETRY_BASE_DELAY: float = 2.0  # 第 1 次等待 2s


@dataclass(frozen=True)
class CookieRecord:
    """Cookie 池中一条记录的内存表示。

    与 ``cookies`` 表一行对应，用于在爬虫层与数据层之间传递 Cookie 状态。
    使用 frozen dataclass 保证跨层传递不可变。
    """

    id: int
    content: str
    label: str | None
    status: CookieStatus
    last_used: str | None
    last_check: str | None
    fail_count: int
    created_at: str


def _cookie_to_record(cookie: Cookie) -> CookieRecord:
    """将数据层 Cookie dataclass 转换为爬虫层 CookieRecord。

    参数:
        cookie: ``app.models.Cookie`` 实例（来自 CookieRepository）。

    返回:
        CookieRecord 实例。

    异常:
        ValueError: cookie.id 为 None（未持久化的 Cookie 不能入池）。
    """
    if cookie.id is None:
        raise ValueError("Cookie 未持久化（id=None），不能转换为 CookieRecord")
    return CookieRecord(
        id=cookie.id,
        content=cookie.content,
        label=cookie.label,
        status=cookie.status,  # type: ignore[arg-type]
        last_used=cookie.last_used,
        last_check=cookie.last_check,
        fail_count=cookie.fail_count,
        created_at=cookie.created_at,
    )


class HttpClient:
    """HTTP 客户端。

    封装 ``curl_cffi.requests.AsyncSession``（impersonate="chrome"），
    提供统一请求入口与 Cookie 池管理。
    通过依赖注入接收 CookieRepository 以操作 Cookie 池。

    Cookie 池策略遵循设计文档 4.3 节：
        - 取用：``status='valid'`` 中最久未用优先（由 CookieRepository.get_valid 实现）
        - 失败上报：``fail_count += 1``，连续 ``MAX_FAIL_COUNT`` 次置 invalid
        - 成功上报：重置 ``fail_count = 0``，更新 ``last_used``
        - 全池失效：``get_cookie_from_pool`` 抛 ``CookieInvalidError``

    风控响应处理见 ``_handle_response``。
    """

    def __init__(
        self,
        cookie_repository: CookieRepository,
        signer: Signer,
        timeout_connect: float = 10.0,
        timeout_read: float = 30.0,
    ) -> None:
        """初始化 HTTP 客户端。

        参数:
            cookie_repository: Cookie 池 Repository（v0.0.1 提供）。
            signer: 签名算法入口（v0.0.2 提供）。
            timeout_connect: 连接超时（秒），默认 10.0。
            timeout_read: 读取超时（秒），默认 30.0。
        """
        # curl_cffi 已在模块顶部导入；impersonate="chrome" 伪造浏览器 TLS 指纹
        # （JA3/JA4），绕过抖音 Janus 风控对 httpx 的 200+空 body 软封禁。
        # timeout 为 (connect, read) 二元组（curl_cffi 语义，见 utils.py）。
        self._cookie_repository = cookie_repository
        self._signer = signer
        self._client = AsyncSession(
            impersonate="chrome",
            allow_redirects=False,  # 原 httpx 的 follow_redirects=False
            timeout=(timeout_connect, timeout_read),
            headers=dict(DEFAULT_HEADERS),
        )
        # 并发信号量：限制同时请求数，平滑流量，避免 burst
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)

    async def close(self) -> None:
        """关闭内部 ``AsyncSession``，释放连接池。

        调用时机：应用退出时（AsyncWorker.stop）。
        """
        # curl_cffi AsyncSession.close 是协程，必须 await
        await self._client.close()
        # 释放信号量（让后续 close 幂等）
        for _ in range(_MAX_CONCURRENT_REQUESTS):
            if self._semaphore.locked():
                self._semaphore.release()

    # === 请求入口 ===

    async def get(
        self,
        url: str,
        params: dict | None = None,
        use_cookie_pool: bool = True,
        cookie: str | None = None,
    ) -> CurlResponse:
        """发起 GET 请求，自动注入签名、Cookie、统一 Headers。

        参数:
            url: 请求 URL（不含查询参数）。
            params: 业务请求参数；本方法会自动追加签名参数。
            use_cookie_pool: 是否从 Cookie 池自动取 Cookie（默认 True）。
            cookie: 显式指定 Cookie（优先级高于池）。

        返回:
            curl_cffi 的 Response（兼容 .status_code/.json()/.headers/.text/.url）。

        异常:
            CookieInvalidError: 池中所有 Cookie 均失效或 461/412 响应。
            RateLimitedError: HTTP 429 限流响应。
            VerifyRequiredError: 响应含滑动验证 HTML。
            NetworkError: 网络异常或 5xx 响应。
        """
        # 步骤 1：签名注入
        sign_params = self._signer.sign(url, params or {})
        full_params = {**(params or {}), **sign_params}

        # 步骤 2：确定 Cookie 来源
        cookie_record: CookieRecord | None = None
        cookie_str: str | None = None
        if cookie is not None:
            # 显式指定 Cookie 优先
            cookie_str = cookie
        elif use_cookie_pool:
            # 从池取 Cookie
            cookie_record = self.get_cookie_from_pool()
            cookie_str = cookie_record.content

        # 步骤 3：构造请求 headers
        headers = dict(DEFAULT_HEADERS)
        if cookie_str is not None:
            headers["Cookie"] = cookie_str

        # 步骤 4：通过 _do_fetch 发起请求（信号量 + 指数退避重试）
        cookie_id = cookie_record.id if cookie_record is not None else None
        try:
            response = await self._do_fetch(url, full_params, headers)
        except RateLimitedError:
            # 429 限流不做 Cookie 切换重试，直接上报
            if cookie_id is not None:
                self.report_cookie_fail(cookie_id)
            raise
        except CurlRequestsError as e:
            logger.error("网络异常: url=%s error=%s", url, type(e).__name__)
            raise NetworkError(f"网络请求失败: {e}") from e

        try:
            return self._handle_response(response, cookie_id)
        except CookieInvalidError:
            # 仅在 461/412 且使用 Cookie 池时尝试切换一次
            if not use_cookie_pool or cookie is not None:
                raise
            return await self._retry_with_next_cookie(url, full_params, headers)

    async def _do_fetch(
        self,
        url: str,
        params: dict,
        headers: dict[str, str],
    ) -> CurlResponse:
        """在信号量保护下发起请求，带指数退避重试。

        重试策略：
            - 仅对网络异常（CurlRequestsError）和 429 限流重试
            - 指数退避：2s / 4s / 8s，最多 3 次
            - 优先使用响应头 Retry-After
            - 461/412/验证 HTML 等业务异常不重试，直接抛出

        参数:
            url: 请求 URL。
            params: 含签名的完整参数。
            headers: 请求头。

        返回:
            curl_cffi 的 Response。

        异常:
            RateLimitedError: 429 且重试耗尽。
            NetworkError: 网络异常且重试耗尽。
            CookieInvalidError / VerifyRequiredError: 不重试，直接抛出。
        """
        last_exc: BaseException | None = None
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            async with self._semaphore:
                try:
                    response = await self._client.get(url, params=params, headers=headers)
                except CurlRequestsError as e:
                    last_exc = e
                    logger.warning(
                        "请求失败 (attempt %d/%d): url=%s error=%s",
                        attempt,
                        _RETRY_MAX_ATTEMPTS,
                        url,
                        type(e).__name__,
                    )
                    if attempt < _RETRY_MAX_ATTEMPTS:
                        wait = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.info("指数退避等待 %.1f 秒后重试", wait)
                        await asyncio.sleep(wait)
                        continue
                    raise NetworkError(
                        f"网络请求失败（重试 {_RETRY_MAX_ATTEMPTS} 次耗尽）: {e}"
                    ) from e
                except asyncio.CancelledError:
                    # 任务取消时立即终止，不继续重试
                    logger.info("请求被取消: url=%s", url)
                    raise

            # 检查响应状态码（在信号量外，避免持有信号量时做耗时处理）
            status = response.status_code
            if status == 429:
                last_exc = RateLimitedError(
                    f"HTTP 429 限流（attempt {attempt}/{_RETRY_MAX_ATTEMPTS}）"
                )
                retry_after = self._parse_retry_after(response)
                wait = (
                    retry_after
                    if retry_after is not None
                    else _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                )
                logger.warning(
                    "限流 429 (attempt %d/%d): url=%s retry_after=%s",
                    attempt,
                    _RETRY_MAX_ATTEMPTS,
                    url,
                    wait,
                )
                if attempt < _RETRY_MAX_ATTEMPTS:
                    logger.info("等待 %.1f 秒后重试", wait)
                    await asyncio.sleep(wait)
                    continue
                raise RateLimitedError(f"请求过于频繁，重试 {_RETRY_MAX_ATTEMPTS} 次耗尽")
            # 200 / 3xx / 461/412 / 其他：返回响应，由上层 get() 的 _handle_response 分类处理
            # （461/412 在 _handle_response 中抛 CookieInvalidError，
            #   再由 get() 的 except 块触发 Cookie 切换）
            return response
        # 不应到达这里：for 循环内每次都会 return/raise/continue
        if last_exc is not None:
            raise last_exc
        raise NetworkError(f"请求失败（重试 {_RETRY_MAX_ATTEMPTS} 次耗尽）")

    @staticmethod
    def _parse_retry_after(response: CurlResponse) -> float | None:
        """从响应头解析 Retry-After（秒），返回 None 表示未提供。

        参数:
            response: 限流响应对象。

        返回:
            Retry-After 秒数（float），无此头返回 None。
        """
        retry_after = response.headers.get("retry-after")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except (TypeError, ValueError):
            return None

    async def _retry_with_next_cookie(
        self,
        url: str,
        full_params: dict,
        headers: dict[str, str],
    ) -> CurlResponse:
        """Cookie 失效后从池中取下一条 Cookie 重试一次。

        参数:
            url: 请求 URL。
            full_params: 含签名的完整参数。
            headers: 基础请求头（不含 Cookie）。

        返回:
            curl_cffi 的 Response。

        异常:
            CookieInvalidError: 池中已无可用 Cookie 或重试仍失败。
            RateLimitedError / VerifyRequiredError / NetworkError: 重试响应的其他异常。
        """
        try:
            next_record = self.get_cookie_from_pool()
        except CookieInvalidError:
            # 池中已无可用 Cookie
            raise
        logger.info("Cookie 自动切换，重试使用 Cookie id=%s", next_record.id)
        retry_headers = {**headers, "Cookie": next_record.content}
        try:
            response = await self._client.get(url, params=full_params, headers=retry_headers)
        except CurlRequestsError as e:
            logger.error("重试网络异常: url=%s error=%s", url, type(e).__name__)
            raise NetworkError(f"网络请求失败: {e}") from e
        return self._handle_response(response, next_record.id)

    # === Cookie 池管理 ===

    def get_cookie_from_pool(self) -> CookieRecord:
        """从 Cookie 池中按"最久未用优先"策略取一条 valid Cookie。

        策略:
            - 仅取 ``status='valid'`` 的记录
            - 按 ``last_used`` 升序，取最早使用的一条（由 CookieRepository.get_valid 实现）
            - 取到后立即更新 ``last_used`` 为当前时间

        返回:
            CookieRecord 实例。

        异常:
            CookieInvalidError: 池中无可用 Cookie（全部 invalid 或池空）。
        """
        cookie = self._cookie_repository.get_valid()
        if cookie is None:
            raise CookieInvalidError("Cookie 池无可用 Cookie")
        # 更新 last_used，标记为刚刚使用
        self._cookie_repository.update_last_used(cookie.id, now_iso())
        logger.debug("从 Cookie 池取用 Cookie id=%s label=%s", cookie.id, cookie.label)
        return _cookie_to_record(cookie)

    def report_cookie_fail(self, cookie_id: int) -> None:
        """上报某条 Cookie 请求失败。

        策略:
            - 该 Cookie ``fail_count += 1``
            - 若 ``fail_count >= MAX_FAIL_COUNT``，置 ``status='invalid'``

        参数:
            cookie_id: 失败的 Cookie 记录 ID。
        """
        cookie = self._cookie_repository.get_by_id(cookie_id)
        if cookie is None:
            logger.warning("上报 Cookie 失败：id=%s 不存在", cookie_id)
            return
        new_fail_count = cookie.fail_count + 1
        self._cookie_repository.update_fail_count(cookie_id, new_fail_count)
        if new_fail_count >= MAX_FAIL_COUNT:
            self._cookie_repository.update_status(cookie_id, "invalid")
            logger.warning(
                "Cookie id=%s 连续失败 %d 次，标记为 invalid",
                cookie_id,
                new_fail_count,
            )
        else:
            logger.debug(
                "Cookie id=%s 失败计数 %d/%d",
                cookie_id,
                new_fail_count,
                MAX_FAIL_COUNT,
            )

    def report_cookie_success(self, cookie_id: int) -> None:
        """上报某条 Cookie 请求成功，重置 fail_count。

        参数:
            cookie_id: 成功的 Cookie 记录 ID。
        """
        self._cookie_repository.update_fail_count(cookie_id, 0)
        self._cookie_repository.update_last_used(cookie_id, now_iso())
        logger.debug("Cookie id=%s 请求成功，fail_count 已重置", cookie_id)

    def check_all_cookies_invalid(self) -> bool:
        """检查池里是否所有 Cookie 都失效（无 valid 记录）。

        返回:
            池中无 valid Cookie 返回 True，否则 False。
        """
        cookie = self._cookie_repository.get_valid()
        return cookie is None

    # === 风控响应处理 ===

    def _handle_response(
        self,
        response: CurlResponse,
        cookie_id: int | None,
    ) -> CurlResponse:
        """对响应进行风控分类，转换为对应异常。

        分类逻辑（按优先级）:
            1. ``status_code in {461, 412}`` → 上报 Cookie 失败，抛 ``CookieInvalidError``
            2. ``status_code == 429`` → 上报 Cookie 失败，抛 ``RateLimitedError``
            3. HTTP 200 + 验证 HTML 特征 → 上报 Cookie 失败，抛 ``VerifyRequiredError``
            4. HTTP 200 + JSON ``status_code != 0`` → 原样返回（业务层处理）
            5. HTTP 200 + 正常数据 → 上报 Cookie 成功，原样返回
            6. 其他 4xx → 抛 ``NetworkError``
            7. 其他 5xx → 抛 ``NetworkError``

        参数:
            response: 响应对象（鸭子类型，需有 .status_code/.headers/.text/.url）。
            cookie_id: 关联的 Cookie ID，None 表示不带 Cookie 请求（不上报）。

        返回:
            成功时返回原 ``response``，供上层解析。

        异常:
            CookieInvalidError: 461/412 风控响应。
            RateLimitedError: 429 限流响应。
            VerifyRequiredError: 响应含验证 HTML。
            NetworkError: 其他 4xx/5xx 错误。
        """
        status = response.status_code

        # 优先级 1：461/412 风控（Cookie 失效）
        if status in RISK_STATUS_CODES:
            if cookie_id is not None:
                self.report_cookie_fail(cookie_id)
            logger.warning("风控响应 %d: url=%s", status, response.url)
            raise CookieInvalidError(f"Cookie 失效或被风控（HTTP {status}）")

        # 优先级 2：429 限流
        if status == 429:
            if cookie_id is not None:
                self.report_cookie_fail(cookie_id)
            logger.warning("限流响应 429: url=%s", response.url)
            raise RateLimitedError("请求过于频繁，触发限流（HTTP 429）")

        # 优先级 3：200 + 验证 HTML
        if status == 200 and self._is_verify_response(response):
            if cookie_id is not None:
                self.report_cookie_fail(cookie_id)
            logger.warning("验证 HTML 响应: url=%s", response.url)
            raise VerifyRequiredError("抖音要求安全验证")

        # 优先级 4 & 5：200 正常响应
        if status == 200:
            # status_code 非 0 的业务错误由上层处理，这里原样返回
            # 但 Cookie 请求本身成功，上报 success
            if cookie_id is not None:
                self.report_cookie_success(cookie_id)
            return response

        # 优先级 6：3xx 重定向（如短链 302），原样返回供调用方读取 Location 头
        if 300 <= status <= 399:
            return response

        # 优先级 7 & 8：其他 4xx/5xx
        logger.warning("HTTP 错误响应 %d: url=%s", status, response.url)
        raise NetworkError(f"HTTP {status} 错误响应")

    @staticmethod
    def _is_verify_response(response: CurlResponse) -> bool:
        """检测响应是否含滑动验证 HTML 特征。

        仅在 Content-Type 非 JSON 时检测，避免对大 JSON 响应做全文扫描。

        参数:
            response: 响应对象（鸭子类型，需有 .headers.get/.text）。

        返回:
            含验证特征返回 True，否则 False。
        """
        content_type = response.headers.get("content-type", "").lower()
        # JSON 响应不走验证 HTML 分支
        if "application/json" in content_type:
            return False
        # 仅在 HTML 或 text 响应中检测
        if "html" not in content_type and "text" not in content_type:
            return False
        try:
            text = response.text
        except (UnicodeDecodeError, ValueError):
            return False
        return any(marker in text for marker in VERIFY_HTML_MARKERS)


# === 分页限速（审计 M11/D3） ===

# 分页请求间隔下限/上限（秒）。翻页循环在并发信号量之外再加一层
# 单位时间速率控制，避免高频脉冲触发抖音 461/412、B 站 -412 风控。
_PAGINATION_THROTTLE_MIN: float = 0.3
_PAGINATION_THROTTLE_MAX: float = 0.8


async def pagination_throttle(
    min_delay: float = _PAGINATION_THROTTLE_MIN,
    max_delay: float = _PAGINATION_THROTTLE_MAX,
) -> None:
    """分页请求间随机限速。

    在每页请求之间插入 ``[min_delay, max_delay)`` 秒随机等待，用随机化
    打破固定间隔的机器特征。限速值远小于单页网络耗时，对抓取吞吐影响
    可忽略，但能显著压低短时请求脉冲。

    参数:
        min_delay: 最小间隔（秒）。
        max_delay: 最大间隔（秒），须大于 min_delay。
    """
    import random

    low, high = min_delay, max(max_delay, min_delay + 0.01)
    await asyncio.sleep(random.uniform(low, high))
