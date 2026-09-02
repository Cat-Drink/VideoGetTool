"""HttpClient 单元测试。

覆盖 CookieRecord、_cookie_to_record、Cookie 池管理、风控响应处理、
get 异步方法。网络响应通过 mock 内部 curl_cffi AsyncSession 实现
（不再用 respx，因为 HttpClient 已从 httpx 迁移到 curl_cffi），
CookieRepository 用内存实现，不依赖真实网络与真实 Cookie。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models import Cookie
from app.repositories import CookieRepository
from crawlers.exceptions import (
    CookieInvalidError,
    NetworkError,
    RateLimitedError,
    VerifyRequiredError,
)
from crawlers.http_client import (
    DEFAULT_HEADERS,
    MAX_FAIL_COUNT,
    RISK_STATUS_CODES,
    VERIFY_HTML_MARKERS,
    CookieRecord,
    HttpClient,
    _cookie_to_record,
)
from tests.conftest import StubSigner

# ==================== 模块常量测试 ====================


class TestModuleConstants:
    """模块级常量契约测试。"""

    def test_default_headers_contains_required_keys(self) -> None:
        """默认请求头含 User-Agent / Referer / Accept / Accept-Language。"""
        required_keys = {"User-Agent", "Referer", "Accept", "Accept-Language"}
        assert required_keys.issubset(DEFAULT_HEADERS.keys())

    def test_default_headers_referer_douyin(self) -> None:
        """Referer 指向抖音首页。"""
        assert DEFAULT_HEADERS["Referer"] == "https://www.douyin.com/"

    def test_default_headers_ua_chrome(self) -> None:
        """User-Agent 为 Chrome Windows 桌面 UA。"""
        assert "Chrome" in DEFAULT_HEADERS["User-Agent"]
        assert "Windows NT 10.0" in DEFAULT_HEADERS["User-Agent"]

    def test_risk_status_codes_contains_461_412(self) -> None:
        """风控状态码集合含 461 与 412。"""
        assert 461 in RISK_STATUS_CODES
        assert 412 in RISK_STATUS_CODES
        assert 200 not in RISK_STATUS_CODES

    def test_verify_html_markers_non_empty(self) -> None:
        """验证 HTML 特征字符串列表非空。"""
        assert len(VERIFY_HTML_MARKERS) > 0
        assert "captcha_verify" in VERIFY_HTML_MARKERS

    def test_max_fail_count_is_3(self) -> None:
        """Cookie 连续失败上限为 3。"""
        assert MAX_FAIL_COUNT == 3


# ==================== CookieRecord dataclass 测试 ====================


class TestCookieRecord:
    """CookieRecord dataclass 测试。"""

    def test_cookie_record_fields(self) -> None:
        """CookieRecord 字段正确赋值。"""
        record = CookieRecord(
            id=1,
            content="ttwid=fake; msToken=fake",
            label="账号A",
            status="valid",
            last_used="2026-07-11T10:00:00",
            last_check=None,
            fail_count=0,
            created_at="2026-07-11T09:00:00",
        )
        assert record.id == 1
        assert record.content == "ttwid=fake; msToken=fake"
        assert record.label == "账号A"
        assert record.status == "valid"
        assert record.fail_count == 0

    def test_cookie_record_is_frozen(self) -> None:
        """CookieRecord 是 frozen dataclass，不可修改。"""
        record = CookieRecord(
            id=1,
            content="x",
            label=None,
            status="valid",
            last_used=None,
            last_check=None,
            fail_count=0,
            created_at="2026-07-11",
        )
        with pytest.raises(AttributeError):
            record.status = "invalid"  # type: ignore[misc]


# ==================== _cookie_to_record 测试 ====================


class TestCookieToRecord:
    """_cookie_to_record 转换函数测试。"""

    def test_convert_persisted_cookie(self) -> None:
        """已持久化的 Cookie（id 非 None）正确转换。"""
        cookie = Cookie(
            id=42,
            content="ttwid=fake",
            label="账号A",
            status="valid",
            last_used="2026-07-11T10:00:00",
            last_check=None,
            fail_count=1,
            created_at="2026-07-11T09:00:00",
        )
        record = _cookie_to_record(cookie)
        assert record.id == 42
        assert record.content == "ttwid=fake"
        assert record.label == "账号A"
        assert record.status == "valid"
        assert record.fail_count == 1
        assert record.last_used == "2026-07-11T10:00:00"

    def test_convert_unpersisted_cookie_raises(self) -> None:
        """未持久化的 Cookie（id=None）抛 ValueError。"""
        cookie = Cookie(
            id=None,
            content="ttwid=fake",
            label=None,
            status="untested",
            last_used=None,
            last_check=None,
            fail_count=0,
            created_at="",
        )
        with pytest.raises(ValueError, match="未持久化"):
            _cookie_to_record(cookie)

    def test_convert_preserves_all_fields(self) -> None:
        """转换后所有字段一一对应。"""
        cookie = Cookie(
            id=1,
            content="content_str",
            label="label_str",
            status="invalid",
            last_used="2026-01-01",
            last_check="2026-01-02",
            fail_count=5,
            created_at="2026-01-03",
        )
        record = _cookie_to_record(cookie)
        assert record.id == cookie.id
        assert record.content == cookie.content
        assert record.label == cookie.label
        assert record.status == cookie.status
        assert record.last_used == cookie.last_used
        assert record.last_check == cookie.last_check
        assert record.fail_count == cookie.fail_count
        assert record.created_at == cookie.created_at


# ==================== Cookie 池管理测试 ====================


class TestCookiePoolManagement:
    """Cookie 池管理方法测试：get_cookie_from_pool / report_* / check_all_*。"""

    def test_get_cookie_from_pool_single(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """单 Cookie 池 → 返回该 Cookie，更新 last_used。"""
        cookie_repo.add(
            Cookie(
                id=None,
                content="ttwid=single",
                label=None,
                status="valid",
                last_used=None,
                last_check=None,
                fail_count=0,
                created_at="2026-07-11",
            )
        )
        client = HttpClient(cookie_repo, stub_signer)
        record = client.get_cookie_from_pool()
        assert record.content == "ttwid=single"
        assert record.status == "valid"
        # last_used 应被更新（非 None）
        updated = cookie_repo.get_by_id(record.id)
        assert updated is not None
        assert updated.last_used is not None

    def test_get_cookie_from_pool_multi_round_robin(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """多 Cookie 池 → 按 last_used 升序取最久未用。"""
        client = HttpClient(cookie_repo, stub_signer)
        # sample_cookies[0] last_used=08:00 比 [1] last_used=10:00 更早
        record = client.get_cookie_from_pool()
        assert record.id == sample_cookies[0].id
        # 第二次取：[0] 的 last_used 刚被更新为 now，此时 [1] 的 10:00 更早
        record2 = client.get_cookie_from_pool()
        assert record2.id == sample_cookies[1].id

    def test_get_cookie_from_pool_empty_raises(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """池空 → 抛 CookieInvalidError。"""
        client = HttpClient(cookie_repo, stub_signer)
        with pytest.raises(CookieInvalidError, match="无可用"):
            client.get_cookie_from_pool()

    def test_get_cookie_from_pool_skips_invalid_and_untested(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """池中仅 invalid 与 untested → 抛 CookieInvalidError（get_valid 仅返回 valid）。"""
        cookie_repo.add(
            Cookie(
                id=None,
                content="invalid_one",
                label=None,
                status="invalid",
                last_used=None,
                last_check=None,
                fail_count=3,
                created_at="2026-07-11",
            )
        )
        cookie_repo.add(
            Cookie(
                id=None,
                content="untested_one",
                label=None,
                status="untested",
                last_used=None,
                last_check=None,
                fail_count=0,
                created_at="2026-07-11",
            )
        )
        client = HttpClient(cookie_repo, stub_signer)
        with pytest.raises(CookieInvalidError):
            client.get_cookie_from_pool()

    def test_report_cookie_fail_below_threshold(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """fail_count 从 0→1，状态仍 valid。"""
        client = HttpClient(cookie_repo, stub_signer)
        # sample_cookies[0] fail_count=0
        client.report_cookie_fail(sample_cookies[0].id)
        updated = cookie_repo.get_by_id(sample_cookies[0].id)
        assert updated is not None
        assert updated.fail_count == 1
        assert updated.status == "valid"

    def test_report_cookie_fail_at_threshold(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """fail_count 从 2→3，状态置 invalid。"""
        cookie_id = cookie_repo.add(
            Cookie(
                id=None,
                content="about_to_fail",
                label=None,
                status="valid",
                last_used=None,
                last_check=None,
                fail_count=2,
                created_at="2026-07-11",
            )
        )
        client = HttpClient(cookie_repo, stub_signer)
        client.report_cookie_fail(cookie_id)
        updated = cookie_repo.get_by_id(cookie_id)
        assert updated is not None
        assert updated.fail_count == 3
        assert updated.status == "invalid"

    def test_report_cookie_fail_nonexistent_id_no_raise(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """不存在的 cookie_id 不抛异常，仅记日志。"""
        client = HttpClient(cookie_repo, stub_signer)
        # 不应抛异常
        client.report_cookie_fail(99999)

    def test_report_cookie_success_resets_fail_count(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """成功上报重置 fail_count = 0，更新 last_used。"""
        cookie_id = cookie_repo.add(
            Cookie(
                id=None,
                content="has_failures",
                label=None,
                status="valid",
                last_used=None,
                last_check=None,
                fail_count=2,
                created_at="2026-07-11",
            )
        )
        client = HttpClient(cookie_repo, stub_signer)
        client.report_cookie_success(cookie_id)
        updated = cookie_repo.get_by_id(cookie_id)
        assert updated is not None
        assert updated.fail_count == 0
        assert updated.last_used is not None

    def test_check_all_cookies_invalid_true_when_no_valid(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """全部 invalid → True。"""
        cookie_repo.add(
            Cookie(
                id=None,
                content="invalid_one",
                label=None,
                status="invalid",
                last_used=None,
                last_check=None,
                fail_count=3,
                created_at="2026-07-11",
            )
        )
        client = HttpClient(cookie_repo, stub_signer)
        assert client.check_all_cookies_invalid() is True

    def test_check_all_cookies_invalid_false_when_has_valid(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """有 valid → False。"""
        client = HttpClient(cookie_repo, stub_signer)
        assert client.check_all_cookies_invalid() is False

    def test_check_all_cookies_invalid_true_when_empty(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """空池 → True。"""
        client = HttpClient(cookie_repo, stub_signer)
        assert client.check_all_cookies_invalid() is True

    def test_cookie_fail_then_success_resets(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """失败 2 次后成功 → fail_count 归 0，下次失败从 1 开始。"""
        client = HttpClient(cookie_repo, stub_signer)
        cid = sample_cookies[0].id  # fail_count=0
        client.report_cookie_fail(cid)  # → 1
        client.report_cookie_fail(cid)  # → 2
        client.report_cookie_success(cid)  # → 0
        client.report_cookie_fail(cid)  # → 1
        updated = cookie_repo.get_by_id(cid)
        assert updated is not None
        assert updated.fail_count == 1
        assert updated.status == "valid"


# ==================== 风控响应处理测试 ====================


def _make_response(
    status_code: int,
    *,
    json_body: dict | None = None,
    text_body: str | None = None,
    content_type: str = "application/json",
) -> httpx.Response:
    """构造测试用 httpx.Response（不发起真实请求）。"""
    if json_body is not None:
        import json

        content = json.dumps(json_body).encode("utf-8")
    elif text_body is not None:
        content = text_body.encode("utf-8")
    else:
        content = b""
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://www.douyin.com/test"),
    )


class TestHandleResponse:
    """_handle_response 风控响应分类测试。"""

    def test_461_raises_cookie_invalid(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """461 → 抛 CookieInvalidError，上报 Cookie 失败。"""
        client = HttpClient(cookie_repo, stub_signer)
        cid = sample_cookies[0].id
        resp = _make_response(461, text_body="blocked", content_type="text/html")
        with pytest.raises(CookieInvalidError, match="461"):
            client._handle_response(resp, cid)
        updated = cookie_repo.get_by_id(cid)
        assert updated is not None
        assert updated.fail_count == 1

    def test_412_raises_cookie_invalid(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """412 → 抛 CookieInvalidError，上报 Cookie 失败。"""
        client = HttpClient(cookie_repo, stub_signer)
        cid = sample_cookies[0].id
        resp = _make_response(412, text_body="blocked", content_type="text/html")
        with pytest.raises(CookieInvalidError, match="412"):
            client._handle_response(resp, cid)
        updated = cookie_repo.get_by_id(cid)
        assert updated is not None
        assert updated.fail_count == 1

    def test_429_raises_rate_limited(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """429 → 抛 RateLimitedError，上报 Cookie 失败。"""
        client = HttpClient(cookie_repo, stub_signer)
        cid = sample_cookies[0].id
        resp = _make_response(429, text_body="rate limited", content_type="text/plain")
        with pytest.raises(RateLimitedError, match="429"):
            client._handle_response(resp, cid)
        updated = cookie_repo.get_by_id(cid)
        assert updated is not None
        assert updated.fail_count == 1

    def test_200_verify_html_raises_verify_required(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """200 + 验证 HTML 特征 → 抛 VerifyRequiredError，上报 Cookie 失败。"""
        client = HttpClient(cookie_repo, stub_signer)
        cid = sample_cookies[0].id
        resp = _make_response(
            200,
            text_body="<html><body>captcha_verify required</body></html>",
            content_type="text/html",
        )
        with pytest.raises(VerifyRequiredError):
            client._handle_response(resp, cid)
        updated = cookie_repo.get_by_id(cid)
        assert updated is not None
        assert updated.fail_count == 1

    def test_200_normal_json_returns_response(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """200 + 正常 JSON → 返回 response，上报 Cookie 成功。"""
        client = HttpClient(cookie_repo, stub_signer)
        cid = sample_cookies[0].id
        resp = _make_response(200, json_body={"status_code": 0, "data": "ok"})
        result = client._handle_response(resp, cid)
        assert result is resp
        updated = cookie_repo.get_by_id(cid)
        assert updated is not None
        assert updated.fail_count == 0

    def test_200_status_code_nonzero_returns_response(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """200 + status_code 非 0 → 原样返回（业务层处理），上报 Cookie 成功。"""
        client = HttpClient(cookie_repo, stub_signer)
        cid = sample_cookies[0].id
        resp = _make_response(200, json_body={"status_code": 4000, "message": "video gone"})
        result = client._handle_response(resp, cid)
        assert result is resp
        # Cookie 请求本身成功，fail_count 应被重置
        updated = cookie_repo.get_by_id(cid)
        assert updated is not None
        assert updated.fail_count == 0

    def test_404_raises_network_error(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """404 → 抛 NetworkError。"""
        client = HttpClient(cookie_repo, stub_signer)
        resp = _make_response(404, text_body="not found", content_type="text/plain")
        with pytest.raises(NetworkError, match="404"):
            client._handle_response(resp, None)

    def test_500_raises_network_error(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """500 → 抛 NetworkError。"""
        client = HttpClient(cookie_repo, stub_signer)
        resp = _make_response(500, text_body="server error", content_type="text/plain")
        with pytest.raises(NetworkError, match="500"):
            client._handle_response(resp, None)

    def test_no_cookie_id_skips_report(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """cookie_id=None 时不上报 Cookie（短链重定向场景）。"""
        client = HttpClient(cookie_repo, stub_signer)
        resp = _make_response(461, text_body="blocked", content_type="text/html")
        # 不抛 CookieRepository 相关异常（因为不上报）
        with pytest.raises(CookieInvalidError):
            client._handle_response(resp, None)

    def test_verify_html_skipped_for_json(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """JSON 响应不走验证 HTML 检测（即使含 captcha_verify 字符串）。"""
        client = HttpClient(cookie_repo, stub_signer)
        # JSON 响应体含 captcha_verify 字符串，但 Content-Type 为 JSON
        resp = _make_response(
            200,
            json_body={"status_code": 0, "msg": "captcha_verify should not trigger"},
        )
        # 应正常返回，不抛 VerifyRequiredError
        result = client._handle_response(resp, None)
        assert result is resp

    def test_verify_html_non_text_content_skipped(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """非 text/html Content-Type 不检测验证 HTML（如二进制响应）。"""
        client = HttpClient(cookie_repo, stub_signer)
        resp = _make_response(
            200,
            text_body="captcha_verify",
            content_type="application/octet-stream",
        )
        # 非 text/html，不检测验证特征，按正常 200 返回
        result = client._handle_response(resp, None)
        assert result is resp


# ==================== get 异步方法测试 ====================

_TEST_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"


def _make_client(
    cookie_repo: CookieRepository,
    stub_signer: StubSigner,
) -> tuple[HttpClient, AsyncMock]:
    """构造 HttpClient 并把内部 curl_cffi AsyncSession 替换为 AsyncMock。

    返回 (client, transport)：transport.get 为 AsyncMock，可设置
    return_value / side_effect，并通过 await_args / await_args_list 断言
    实际传给 AsyncSession.get 的 params / headers（含签名与 Cookie）。
    """
    client = HttpClient(cookie_repo, stub_signer)
    transport = AsyncMock(name="AsyncSession")
    client._client = transport
    return client, transport


def _make_resp(status_code: int, **kwargs: object) -> httpx.Response:
    """构造带 request 的 httpx.Response，确保 .url 可访问。

    ``_handle_response`` 在 461/429/验证HTML/4xx/5xx 分支会读取
    ``response.url`` 记日志；不带 request 的 httpx.Response 访问 .url 会抛
    RuntimeError，因此这里统一带上请求实例。
    """
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", _TEST_URL),
        **kwargs,
    )


class TestHttpGet:
    """get 异步方法测试：签名/Cookie 注入、风控响应、自动切换。

    通过 mock 内部 ``AsyncSession``（curl_cffi）隔离网络层。
    """

    async def test_get_injects_signature(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """验证 signer.sign 被调用且签名参数追加到请求 params。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = httpx.Response(200, json={"status_code": 0, "data": "ok"})
        await client.get(_TEST_URL, {"aweme_id": "123"})
        # StubSigner 记录了调用参数
        assert stub_signer.call_count == 1
        assert stub_signer.last_url == _TEST_URL
        assert stub_signer.last_params == {"aweme_id": "123"}
        # 验证签名参数出现在传给 AsyncSession.get 的 params 中
        call = transport.get.await_args
        assert call is not None
        params = call.kwargs["params"]
        assert "X-Bogus" in params
        assert "a_bogus" in params
        assert "msToken" in params

    async def test_get_injects_cookie_from_pool(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """use_cookie_pool=True → Cookie 头存在且为池中 Cookie 内容。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = httpx.Response(200, json={"status_code": 0})
        await client.get(_TEST_URL, {"aweme_id": "123"})
        call = transport.get.await_args
        assert call is not None
        # sample_cookies[0] 是最久未用的，应被取用
        assert call.kwargs["headers"]["Cookie"] == sample_cookies[0].content

    async def test_get_with_explicit_cookie(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """cookie= 显式指定 → 不调用池，Cookie 头为指定值。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = httpx.Response(200, json={"status_code": 0})
        explicit_cookie = "ttwid=explicit; msToken=explicit"
        await client.get(_TEST_URL, {"aweme_id": "123"}, cookie=explicit_cookie)
        call = transport.get.await_args
        assert call is not None
        assert call.kwargs["headers"]["Cookie"] == explicit_cookie

    async def test_get_without_cookie(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """use_cookie_pool=False, cookie=None → 不带 Cookie 头（短链重定向场景）。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = httpx.Response(200, json={"status_code": 0})
        await client.get(_TEST_URL, {"aweme_id": "123"}, use_cookie_pool=False)
        call = transport.get.await_args
        assert call is not None
        assert "Cookie" not in call.kwargs["headers"]

    async def test_get_success_reports_cookie_success(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """200 + status_code=0 → 调用 report_cookie_success，fail_count 重置。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = httpx.Response(200, json={"status_code": 0})
        # 先把 fail_count 设为 1
        cookie_repo.update_fail_count(sample_cookies[0].id, 1)
        await client.get(_TEST_URL, {"aweme_id": "123"})
        updated = cookie_repo.get_by_id(sample_cookies[0].id)
        assert updated is not None
        assert updated.fail_count == 0

    async def test_get_461_triggers_auto_switch(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """首条 Cookie 461 失效 → 自动取下一条重试成功。"""
        # 第一次返回 461，第二次返回 200
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.side_effect = [
            _make_resp(461, text="blocked", headers={"content-type": "text/html"}),
            httpx.Response(200, json={"status_code": 0}),
        ]
        response = await client.get(_TEST_URL, {"aweme_id": "123"})
        assert response.status_code == 200
        # 应该有两次请求
        assert transport.get.await_count == 2
        calls = transport.get.await_args_list
        # 第一次用 sample_cookies[0]，第二次用 sample_cookies[1]
        assert calls[0].kwargs["headers"]["Cookie"] == sample_cookies[0].content
        assert calls[1].kwargs["headers"]["Cookie"] == sample_cookies[1].content
        # 首条 Cookie fail_count += 1
        first = cookie_repo.get_by_id(sample_cookies[0].id)
        assert first is not None
        assert first.fail_count == 1

    async def test_get_all_cookies_invalid_raises(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """池中无 valid Cookie → 抛 CookieInvalidError（不发起网络请求）。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = httpx.Response(200, json={"status_code": 0})
        with pytest.raises(CookieInvalidError, match="无可用"):
            await client.get(_TEST_URL, {"aweme_id": "123"})
        # 池取 Cookie 失败应直接抛，不走到网络层
        transport.get.assert_not_awaited()

    async def test_get_461_no_pool_no_retry(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """use_cookie_pool=False 时 461 不触发自动切换，直接抛异常。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = _make_resp(
            461, text="blocked", headers={"content-type": "text/html"}
        )
        with pytest.raises(CookieInvalidError):
            await client.get(_TEST_URL, {"aweme_id": "123"}, use_cookie_pool=False)
        # 仅一次请求，无重试
        assert transport.get.await_count == 1

    async def test_get_network_exception_raises_network_error(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """curl_cffi RequestException → 抛 NetworkError。"""
        from curl_cffi.requests.exceptions import RequestException as CurlReqErr

        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.side_effect = CurlReqErr("connection refused")
        with pytest.raises(NetworkError):
            await client.get(_TEST_URL, {"aweme_id": "123"})

    async def test_get_default_headers_present(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """验证 User-Agent / Referer / Accept 头存在。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = httpx.Response(200, json={"status_code": 0})
        await client.get(_TEST_URL, {"aweme_id": "123"})
        call = transport.get.await_args
        assert call is not None
        headers = call.kwargs["headers"]
        assert "User-Agent" in headers
        assert headers["Referer"] == "https://www.douyin.com/"
        assert "Accept" in headers

    async def test_get_429_raises_rate_limited(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """429 → 指数退避重试 3 次耗尽后抛 RateLimitedError，不触发 Cookie 自动切换。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = _make_resp(
            429, text="rate limited", headers={"content-type": "text/plain", "retry-after": "2"}
        )
        with pytest.raises(RateLimitedError):
            await client.get(_TEST_URL, {"aweme_id": "123"})
        # _do_fetch 最多重试 3 次，429 不触发 Cookie 切换
        assert transport.get.await_count == 3

    async def test_get_403_retries_then_raises_network_error(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """403 → 较短退避重试 3 次耗尽后抛 NetworkError，不触发 Cookie 切换/失败上报。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = _make_resp(
            403,
            text="forbidden",
            headers={"content-type": "text/plain", "retry-after": "0"},
        )
        with pytest.raises(NetworkError, match="403"):
            await client.get(_TEST_URL, {"aweme_id": "123"})
        # _do_fetch 最多重试 3 次，403 不触发 Cookie 切换
        assert transport.get.await_count == 3
        # 403 不视为 Cookie 失效，fail_count 保持不变
        updated = cookie_repo.get_by_id(sample_cookies[0].id)
        assert updated is not None
        assert updated.fail_count == 0

    async def test_get_403_uses_short_backoff(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """403 无 Retry-After → 退避 1s / 2s（第 1 次 1s、第 2 次 2s），共 3 次尝试。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = _make_resp(
            403, text="forbidden", headers={"content-type": "text/plain"}
        )
        sleeps: list[float] = []

        async def _fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        with (
            patch.object(asyncio, "sleep", side_effect=_fake_sleep),
            pytest.raises(NetworkError, match="403"),
        ):
            await client.get(_TEST_URL, {"aweme_id": "123"})
        assert sleeps == [1.0, 2.0]
        assert transport.get.await_count == 3

    async def test_get_403_then_success_returns_response(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """403 后重试成功（403 → 200）→ 返回 200 响应，仅发起 2 次请求。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.side_effect = [
            _make_resp(
                403,
                text="forbidden",
                headers={"content-type": "text/plain", "retry-after": "0"},
            ),
            httpx.Response(200, json={"status_code": 0}),
        ]
        response = await client.get(_TEST_URL, {"aweme_id": "123"})
        assert response.status_code == 200
        assert transport.get.await_count == 2

    async def test_get_verify_html_raises_verify_required(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """200 + 验证 HTML → 抛 VerifyRequiredError。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = _make_resp(
            200,
            text="<html>captcha_verify</html>",
            headers={"content-type": "text/html"},
        )
        with pytest.raises(VerifyRequiredError):
            await client.get(_TEST_URL, {"aweme_id": "123"})

    async def test_get_status_code_nonzero_returns_response(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """200 + status_code 非 0 → 返回 response（不抛异常）。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = httpx.Response(
            200, json={"status_code": 4000, "message": "gone"}
        )
        response = await client.get(_TEST_URL, {"aweme_id": "123"})
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 4000

    async def test_get_500_raises_network_error(
        self,
        sample_cookies: list[Cookie],
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """500 → 抛 NetworkError。"""
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = _make_resp(
            500, text="server error", headers={"content-type": "text/plain"}
        )
        with pytest.raises(NetworkError):
            await client.get(_TEST_URL, {"aweme_id": "123"})

    async def test_get_auto_switch_exhausted_raises(
        self,
        cookie_repo: CookieRepository,
        stub_signer: StubSigner,
    ) -> None:
        """首条 Cookie 461 失效，池中仅 1 条 valid → 自动切换无第二条 → 抛 CookieInvalidError。"""
        cookie_repo.add(
            Cookie(
                id=None,
                content="only_valid",
                label=None,
                status="valid",
                last_used=None,
                last_check=None,
                fail_count=0,
                created_at="2026-07-11",
            )
        )
        client, transport = _make_client(cookie_repo, stub_signer)
        transport.get.return_value = _make_resp(
            461, text="blocked", headers={"content-type": "text/html"}
        )
        with pytest.raises(CookieInvalidError):
            await client.get(_TEST_URL, {"aweme_id": "123"})
