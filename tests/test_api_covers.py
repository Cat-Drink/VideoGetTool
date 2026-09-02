"""封面图片代理端点测试。

覆盖：
    - _validate_url 的 SSRF 防护（协议/回环/私网/链路本地拦截）
    - proxy_cover 抓取成功时返回图片字节与正确 Content-Type
    - 上游非 200 / 非图片 Content-Type 时的错误处理
    - 响应体大小上限保护
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api.covers import (
    _BENCHMARK_NETWORK,
    _MAX_COVER_BYTES,
    _is_blocked_ip,
    _validate_url,
    router,
)


def _make_iter_bytes(body: bytes):
    """构造一个同步返回 async generator 的 aiter_bytes 替身。"""

    async def _aiter_bytes(_=None):
        yield body

    return _aiter_bytes


# === _validate_url SSRF 防护 ===


class TestValidateUrl:
    """URL 校验与 SSRF 防护。"""

    @pytest.mark.parametrize(
        "url",
        [
            "https://i0.hdslb.com/bfs/archive/cover.jpg",
            "http://i1.hdslb.com/bfs/archive/cover.jpg",
            "https://p3-sign.douyinpic.com/aweme/cover.jpeg",
        ],
    )
    def test_allows_public_http_https(self, url: str) -> None:
        """允许公网 http/https 图片地址。"""
        assert _validate_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/a.jpg",
            "data:image/png;base64,AAAA",
            "javascript:alert(1)",
            "",
        ],
    )
    def test_rejects_non_http_schemes(self, url: str) -> None:
        """拒绝非 http/https 协议（防 SSRF 与协议走私）。"""
        with pytest.raises(HTTPException) as exc:
            _validate_url(url)
        assert exc.value.status_code == 400

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:18989/api/health",
            "http://localhost:18989/api/health",
            "http://10.0.0.5/secret",
            "http://192.168.1.1/admin",
            "http://169.254.169.254/latest/meta-data",
            "http://172.16.0.1/x",
        ],
    )
    def test_rejects_loopback_private(self, url: str) -> None:
        """拒绝回环/私网/链路本地地址（防 SSRF）。"""
        with pytest.raises(HTTPException) as exc:
            _validate_url(url)
        assert exc.value.status_code == 400

    def test_rejects_oversized_url(self) -> None:
        """拒绝超长 URL。"""
        long_url = "https://example.com/" + "a" * 5000
        with pytest.raises(HTTPException) as exc:
            _validate_url(long_url)
        assert exc.value.status_code == 400

    def test_allows_benchmark_range_for_proxy(self) -> None:
        """放行 RFC 2544 基准测试网段（198.18.0.0/15）。

        Clash / sing-box / V2Ray 等 TUN 模式透明代理使用该网段作为虚拟网关
        地址，抖音封面 CDN（douyinpic.com）在代理环境下解析到 198.18.0.x。
        Python ipaddress 将 is_private 判定为 True，若不显式放行，
        /covers 代理会误拦截封面图，导致列表项预览图不显示。
        """
        # 网段内任意地址都不应被 _is_blocked_ip 拦截
        assert not _is_blocked_ip("198.18.0.1")
        assert not _is_blocked_ip("198.18.0.206")
        assert not _is_blocked_ip("198.19.255.255")
        # 真正的私网/回环地址仍须拦截
        assert _is_blocked_ip("10.0.0.5")
        assert _is_blocked_ip("127.0.0.1")
        assert _is_blocked_ip("192.168.1.1")
        assert _is_blocked_ip("172.16.0.1")
        assert _is_blocked_ip("169.254.169.254")
        # 公开 IP 放行
        assert not _is_blocked_ip("8.8.8.8")
        assert not _is_blocked_ip("1.1.1.1")
        # 网段常量本身可识别
        assert _BENCHMARK_NETWORK.num_addresses > 0


# === proxy_cover 端点 ===


@pytest.fixture
def api_client():
    """只挂载 covers router 的 TestClient。"""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


class TestProxyCover:
    """封面代理端点行为。"""

    def test_returns_image_bytes(self, api_client) -> None:
        """抓取成功时返回图片字节与 image/jpeg。"""
        # JPEG SOI + SOI0 marker + payload
        body = bytes.fromhex("ffd8ffe0") + b"fakejpeg"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "image/jpeg"}
        mock_resp.aiter_bytes = _make_iter_bytes(body)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = api_client.get(
                "/api/covers",
                params={"url": "https://i0.hdslb.com/bfs/archive/cover.jpg"},
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/jpeg")
        assert resp.content == body
        assert "cache-control" in resp.headers

    def test_returns_400_for_ssrf_target(self, api_client) -> None:
        """SSRF 目标返回 400。"""
        resp = api_client.get(
            "/api/covers",
            params={"url": "http://127.0.0.1:18989/api/health"},
        )
        assert resp.status_code == 400

    def test_missing_url_returns_422(self, api_client) -> None:
        """缺少必填 url 参数时 FastAPI 校验返回 422。"""
        resp = api_client.get("/api/covers")
        assert resp.status_code == 422

    def test_upstream_non_200_returns_502(self, api_client) -> None:
        """上游非 200 时返回 502。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.headers = {}
        mock_resp.aiter_bytes = _make_iter_bytes(b"forbidden")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = api_client.get(
                "/api/covers",
                params={"url": "https://i0.hdslb.com/bfs/archive/cover.jpg"},
            )

        assert resp.status_code == 502

    def test_upstream_non_image_content_type_returns_502(self, api_client) -> None:
        """上游返回非图片 Content-Type 时返回 502。"""
        body = b"<html>not an image</html>"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.aiter_bytes = _make_iter_bytes(body)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = api_client.get(
                "/api/covers",
                params={"url": "https://i0.hdslb.com/bfs/archive/cover.jpg"},
            )

        assert resp.status_code == 502

    def test_oversized_body_returns_413(self, api_client) -> None:
        """响应体超过上限时返回 413。"""
        # 构造超过大小上限的单块（流式接收时第二次累加判定会触发）
        body = b"x" * (_MAX_COVER_BYTES + 1)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "image/jpeg"}
        mock_resp.aiter_bytes = _make_iter_bytes(body)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = api_client.get(
                "/api/covers",
                params={"url": "https://i0.hdslb.com/bfs/archive/cover.jpg"},
            )

        assert resp.status_code == 413
