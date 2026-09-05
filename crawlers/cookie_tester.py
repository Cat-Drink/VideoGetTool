"""Cookie 测试器模块。

通过调用轻量抖音 Web API 验证 Cookie 是否有效，返回结构化的
``CookieTestResult``。供工作线程层 / UI 层组合调用 ``CookieRepository``
完成"测试 Cookie"功能。

接口契约见 ``docs/structure/05-接口设计文档.md`` 第 7.3 节；
实现规范见 ``docs/plans/v0.0.4-视频解析与主页抓取.md`` 第 5 节。

设计要点:
    - 通过依赖注入接收 HttpClient 与 Signer，不持有网络连接
    - HTTP 层风控（461/412/429/验证 HTML/网络异常）由 HttpClient 抛出，
      本类 catch 后统一返回 ``is_valid=False``，错误信息区分场景
    - 不引入第三种状态（与接口文档 7.3 节"无法判定 → untested"略有差异，
      见计划文档 5.4 节说明）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.logger import get_logger
from crawlers import api_spec
from crawlers.exceptions import (
    CookieInvalidError,
    NetworkError,
    RateLimitedError,
    VerifyRequiredError,
)
from crawlers.utils import safe_int

if TYPE_CHECKING:
    from crawlers.http_client import HttpClient
    from crawlers.signer import Signer

logger = get_logger(__name__)


# === 数据结构 ===


@dataclass(frozen=True)
class CookieTestResult:
    """Cookie 测试结果。

    属性:
        is_valid: Cookie 是否有效。
        error_message: 无效时的具体错误信息；有效时为空字符串。
        user_nickname: 有效时返回当前登录用户昵称（若 API 响应包含）；
            无效或无法获取时为 None。
    """

    is_valid: bool
    error_message: str
    user_nickname: str | None


# === CookieTester 类 ===


class CookieTester:
    """Cookie 测试器。

    推荐使用 ``aweme/v1/web/general/search/single/`` 接口验证 Cookie
    有效性（轻量、风控较弱）。

    验证逻辑（见计划文档 5.4 节）:
        - HTTP 200 + ``status_code == 0`` → 有效
        - HTTP 461/412 → 无效（"Cookie 失效或被限流"）
        - HTTP 429 → 无效（"请求过于频繁"）
        - HTTP 200 + ``status_code != 0`` → 无效（status_msg）
        - HTTP 200 + 验证 HTML → 无效（"触发抖音安全验证"）
        - httpx 网络异常 → 无效（"网络异常：{具体描述}"）

    ``user_nickname`` 提取:
        search/single 接口响应通常不含用户昵称，需调用备选接口
        ``USER_PROFILE_SELF_URL`` 获取。本类优先用 search/single 验证有效性，
        ``user_nickname`` 字段在无法获取时返回 None，不阻塞验证流程。
    """

    def __init__(self, http_client: HttpClient, signer: Signer) -> None:
        """初始化 Cookie 测试器。

        参数:
            http_client: HttpClient 实例（提供签名 + Cookie 注入的请求能力）。
            signer: Signer 实例（保留注入以便未来扩展）。
        """
        self._http_client = http_client
        self._signer = signer

    @staticmethod
    def _build_test_params() -> dict:
        """构造 search 接口业务参数。

        返回:
            含 keyword/count/offset 与所有固定参数的字典。
        """
        return {
            "keyword": api_spec.COOKIE_TEST_SEARCH_KEYWORD,
            "count": str(api_spec.COOKIE_TEST_SEARCH_COUNT),
            "offset": str(api_spec.COOKIE_TEST_SEARCH_OFFSET),
            **api_spec.COMMON_FIXED_PARAMS,
        }

    @staticmethod
    def _extract_user_nickname(payload: dict) -> str | None:
        """从响应中尝试提取用户昵称。

        search/single 响应通常不含用户昵称；本方法预留兼容路径，
        当响应顶层含 ``user_nickname`` / ``user.nickname`` 时返回。

        参数:
            payload: 响应 JSON。

        返回:
            昵称字符串；无法获取返回 None。
        """
        nickname = payload.get("user_nickname")
        if isinstance(nickname, str) and nickname:
            return nickname
        user = payload.get("user")
        if isinstance(user, dict):
            nickname = user.get("nickname")
            if isinstance(nickname, str) and nickname:
                return nickname
        return None

    async def test_cookie(self, cookie_content: str) -> CookieTestResult:
        """测试单个 Cookie 是否有效。

        参数:
            cookie_content: 待测试的 Cookie 字符串。

        返回:
            CookieTestResult：
                - 有效：``is_valid=True, error_message="", user_nickname=...``
                - 无效/网络异常：``is_valid=False, error_message=<详情>``
        """
        params = self._build_test_params()
        logger.info("测试 Cookie 有效性")

        # 调用 search 接口；HttpClient 已统一处理风控异常
        try:
            response = await self._http_client.get(
                api_spec.GENERAL_SEARCH_URL,
                params=params,
                use_cookie_pool=False,
                cookie=cookie_content,
            )
        except CookieInvalidError as e:
            logger.warning("Cookie 测试失败：Cookie 失效或被限流: %s", e)
            return CookieTestResult(
                is_valid=False,
                error_message="Cookie 失效或被限流",
                user_nickname=None,
            )
        except RateLimitedError as e:
            logger.warning("Cookie 测试失败：触发限流: %s", e)
            return CookieTestResult(
                is_valid=False,
                error_message="请求过于频繁，请稍后重试",
                user_nickname=None,
            )
        except VerifyRequiredError as e:
            logger.warning("Cookie 测试失败：触发安全验证: %s", e)
            return CookieTestResult(
                is_valid=False,
                error_message="触发抖音安全验证",
                user_nickname=None,
            )
        except NetworkError as e:
            logger.warning("Cookie 测试失败：网络异常: %s", e)
            return CookieTestResult(
                is_valid=False,
                error_message=f"网络异常：{e}",
                user_nickname=None,
            )

        # HTTP 200 后才到这里：解析 JSON
        try:
            payload = response.json()
        except ValueError as e:
            logger.error("Cookie 测试响应 JSON 解析失败: %s", e)
            return CookieTestResult(
                is_valid=False,
                error_message=f"网络异常：响应非 JSON ({e})",
                user_nickname=None,
            )

        status_code = payload.get("status_code")
        # 审计 S8：抖音 API 有时返回字符串/非数字，用 safe_int 防 ValueError
        if safe_int(status_code) != 0:
            status_msg = payload.get("status_msg") or "未知错误"
            logger.warning("Cookie 测试失败：status_code=%s msg=%s", status_code, status_msg)
            return CookieTestResult(
                is_valid=False,
                error_message=str(status_msg),
                user_nickname=None,
            )

        # 验证通过
        nickname = self._extract_user_nickname(payload)
        logger.info("Cookie 测试通过，nickname=%s", nickname)
        return CookieTestResult(
            is_valid=True,
            error_message="",
            user_nickname=nickname,
        )

    async def test_all(self, cookies: list[tuple[int, str]]) -> list[tuple[int, CookieTestResult]]:
        """批量测试多个 Cookie。

        内部用 ``asyncio.gather`` 并发测试（受 HttpClient 内部 Semaphore 约束）。

        参数:
            cookies: ``(cookie_id, cookie_content)`` 列表。

        返回:
            ``(cookie_id, CookieTestResult)`` 列表，顺序与输入一致。
        """
        import asyncio

        async def _test_one(cookie_id: int, content: str) -> tuple[int, CookieTestResult]:
            result = await self.test_cookie(content)
            return (cookie_id, result)

        tasks = [_test_one(cid, content) for cid, content in cookies]
        return await asyncio.gather(*tasks)
