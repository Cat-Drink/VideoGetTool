"""封面图片代理端点测试。

覆盖：
    - _validate_url 的 SSRF 防护（协议/回环/私网/链路本地拦截）
    - proxy_cover 抓取成功时返回图片字节与正确 Content-Type
    - 上游非 200 / 非图片 Content-Type 时的错误处理
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api.covers import _validate_url, proxy_cover, router


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
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"\xff\xd8\xff\xe0fakejpeg"
        mock_resp.headers = {"content-type": "image/jpeg"}

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
        assert resp.content == b"\xff\xd8\xff\xe0fakejpeg"
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
        mock_resp.content = b"forbidden"
        mock_resp.headers = {}

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
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html>not an image</html>"
        mock_resp.headers = {"content-type": "text/html"}

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
