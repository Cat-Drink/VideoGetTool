"""B 站 HTTP 客户端模块。

封装 httpx.AsyncClient，统一注入 B 站请求头（UA / Referer / Cookie / buvid3），
提供异步 GET 入口与 B 站业务错误码处理。

与抖音的 HttpClient 不同，B 站不需要 X-Bogus / A-Bogus 签名，
只需 WBI 签名（由 BiliSigner 注入）与 buvid3 指纹。

业务错误处理:
    - HTTP 412 → RateLimitedError（触发限流）
    - HTTP 403 → CookieInvalidError（权限不足/风控）
    - JSON code != 0 → 业务错误，抛 BiliAPIError
    - HTTP 200 + code == 0 → 正常返回
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from app.logger import get_logger
from crawlers.bilibili.constants import (
    DEFAULT_HEADERS,
    REQUEST_TIMEOUT_CONNECT,
    REQUEST_TIMEOUT_READ,
)
from crawlers.exceptions import (
    CookieInvalidError,
    NetworkError,
    RateLimitedError,
)

if TYPE_CHECKING:
    from crawlers.bilibili.bili_signer import BiliSigner

logger = get_logger(__name__)

# === 模块级常量 ===

# B 站风控/错误 HTTP 状态码
_RISK_STATUS_CODES: frozenset[int] = frozenset({412, 403})


class BiliAPIError(Exception):
    """B 站 API 业务错误（HTTP 200 但 code != 0）。

    属性:
        code: B 站业务错误码（如 -404 视频不存在, -403 权限不足, -412 风控）。
        message: 错误消息。
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"B 站 API 错误 [{code}]: {message}")
        self.code = code
        self.message = message


class BiliHttpClient:
    """B 站 HTTP 客户端。

    通过依赖注入接收 BiliSigner 与可选 Cookie 字符串，提供：
        - get_json(): 发起 GET 并解析 JSON（自动 WBI 签名 + buvid3 注入）
        - get_raw(): 发起 GET 返回原始响应（用于下载媒体流）
    """

    def __init__(
        self,
        signer: BiliSigner,
        cookie: str | None = None,
        timeout_connect: float = REQUEST_TIMEOUT_CONNECT,
        timeout_read: float = REQUEST_TIMEOUT_READ,
    ) -> None:
        """初始化 B 站 HTTP 客户端。

        参数:
            signer: WBI 签名器（注入签名能力）。
            cookie: B 站 Cookie 字符串（可选，为 None 时不携带 Cookie）。
            timeout_connect: 连接超时（秒）。
            timeout_read: 读取超时（秒）。
        """
        self._signer = signer
        self._cookie = cookie or ""
        # 构造时生成一次 buvid3 并在客户端生命周期内复用，
        # 更贴近真实设备指纹，降低 B 站风控触发概率。
        self._buvid3: str = signer.generate_buvid3()
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(
                connect=timeout_connect,
                read=timeout_read,
                write=10.0,
                pool=5.0,
            ),
            follow_redirects=True,
            headers=dict(DEFAULT_HEADERS),
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """暴露底层 httpx.AsyncClient，供 signer 刷新密钥等场景复用。

        供 BiliSigner.refresh_keys 等需要复用同一连接池的调用方使用，
        避免外部直接访问私有 _client 属性。
        """
        return self._client

    async def close(self) -> None:
        """关闭内部 httpx.AsyncClient，释放连接池。"""
        await self._client.aclose()

    def set_cookie(self, cookie: str) -> None:
        """更新 Cookie 字符串（运行时切换）。"""
        self._cookie = cookie or ""

    # === 请求入口 ===

    async def get_raw(
        self,
        url: str,
        params: dict | None = None,
        signed: bool = True,
        additional_headers: dict[str, str] | None = None,
        cookie: str | None = None,
    ) -> httpx.Response:
        """发起 GET 请求，返回原始 httpx.Response。

        参数:
            url: 请求 URL。
            params: 业务请求参数；signed=True 时自动追加 WBI 签名。
            signed: 是否附加 WBI 签名（默认 True）。
            additional_headers: 附加请求头（需下载媒体流传 Referer 时使用）。
            cookie: 本次请求使用的 B 站 Cookie（可选）。
                传入时仅对当前请求生效，不修改共享客户端状态，避免并发互踩。

        返回:
            httpx.Response。

        异常:
            CookieInvalidError: HTTP 403 响应。
            RateLimitedError: HTTP 412 响应。
            NetworkError: 网络异常或 5xx 响应。
        """
        # 步骤 1：WBI 签名注入
        full_params = dict(params or {})
        if signed:
            try:
                full_params = self._signer.sign(full_params)
            except Exception:
                # 签名失败时先尝试刷新密钥再签一次
                await self._signer.refresh_keys(self._client)
                full_params = self._signer.sign(dict(params or {}))

        # 步骤 2：构造请求头
        headers = dict(DEFAULT_HEADERS)
        if additional_headers:
            headers.update(additional_headers)

        # 步骤 3：携带 Cookie + buvid3（优先使用每请求 Cookie，避免共享状态互踩）
        effective_cookie = cookie if cookie is not None else self._cookie
        cookies = {}
        if effective_cookie:
            # 解析 Cookie 字符串为键值（简单切分首个 =）
            for part in effective_cookie.split(";"):
                part = part.strip()
                if not part:
                    continue
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k.strip()] = v.strip()
        if "buvid3" not in cookies:
            cookies["buvid3"] = self._buvid3

        # 步骤 4：发起请求
        try:
            response = await self._client.get(
                url, params=full_params, headers=headers, cookies=cookies
            )
        except httpx.HTTPError as e:
            logger.error("B 站网络异常: url=%s error=%s", url, type(e).__name__)
            raise NetworkError(f"B 站网络请求失败: {e}") from e

        return self._handle_response(response)

    async def get_json(
        self,
        url: str,
        params: dict | None = None,
        signed: bool = True,
        cookie: str | None = None,
    ) -> dict:
        """发起 GET 并解析 JSON 响应。

        参数:
            url: 请求 URL。
            params: 业务请求参数。
            signed: 是否附加 WBI 签名。
            cookie: 本次请求使用的 B 站 Cookie（可选），仅当前请求生效。

        返回:
            响应的 `data` 字段（dict）。

        异常:
            BiliAPIError: code != 0 的业务错误。
            CookieInvalidError / RateLimitedError / NetworkError: 见 get_raw()。
        """
        response = await self.get_raw(url, params, signed=signed, cookie=cookie)
        try:
            payload = response.json()
        except ValueError as e:
            raise NetworkError("B 站响应不是合法 JSON") from e

        code = payload.get("code", 0)
        if code != 0:
            message = payload.get("message", "") or payload.get("msg", "") or "未知错误"
            raise BiliAPIError(code, message)

        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    # === 响应处理 ===

    def _handle_response(self, response: httpx.Response) -> httpx.Response:
        """对 httpx 响应进行错误分类。

        分类逻辑:
            1. status == 412 → RateLimitedError
            2. status == 403 → CookieInvalidError
            3. 其他 4xx / 5xx → NetworkError
            4. 2xx → 原样返回
        """
        status = response.status_code

        # 风控/限流
        if status == 412:
            logger.warning("B 站限流响应 412: url=%s", response.url)
            raise RateLimitedError("请求过于频繁，触发 B 站限流（HTTP 412）")

        # 权限不足 / Cookie 失效
        if status == 403:
            logger.warning("B 站权限/风控响应 403: url=%s", response.url)
            raise CookieInvalidError("B 站请求被拒绝（HTTP 403），Cookie 可能失效")

        # 其他错误
        if status >= 400:
            logger.warning("B 站 HTTP 错误 %d: url=%s", status, response.url)
            raise NetworkError(f"B 站 HTTP {status} 错误响应")

        return response
