"""安全加固测试：Host 守卫中间件 + WebSocket Origin/连接上限（审计 P0-1/P0-2/N4）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app() -> FastAPI:
    """挂载 HostGuardMiddleware 的最小应用。"""
    from backend.security import HostGuardMiddleware

    app = FastAPI()
    app.add_middleware(HostGuardMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


class TestHostGuardMiddleware:
    """Host 头守卫：白名单放行、非白名单/缺失拒绝（DNS rebinding 防护）。"""

    def test_allowed_hosts_pass(self):
        client = TestClient(_build_app())
        for host in ("127.0.0.1:18989", "127.0.0.1", "localhost:18989", "localhost"):
            resp = client.get("/ping", headers={"host": host})
            assert resp.status_code == 200, host
            assert resp.json() == {"ok": True}

    def test_case_insensitive_host(self):
        client = TestClient(_build_app())
        resp = client.get("/ping", headers={"host": "127.0.0.1:18989 "})
        # 尾部空白被 strip，仍应放行
        assert resp.status_code == 200

    def test_evil_host_rejected(self):
        """DNS rebinding 场景：Host 为攻击者域名必须 403。"""
        client = TestClient(_build_app())
        for host in ("evil.com:18989", "evil.com", "127.0.0.1.evil.com:18989"):
            resp = client.get("/ping", headers={"host": host})
            assert resp.status_code == 403, host

    def test_missing_host_rejected(self):
        client = TestClient(_build_app())
        resp = client.get("/ping", headers={"host": ""})
        assert resp.status_code == 403

    def test_is_host_allowed_helper(self):
        from backend.security import is_host_allowed

        assert is_host_allowed("127.0.0.1:18989") is True
        assert is_host_allowed("LOCALHOST") is True
        assert is_host_allowed("evil.com:18989") is False
        assert is_host_allowed(None) is False
        assert is_host_allowed("") is False


class TestWebSocketSecurity:
    """WS 端点：Host/Origin 白名单校验与连接数上限。"""

    def _ws_app(self) -> FastAPI:
        from backend.api.ws import router

        app = FastAPI()
        app.include_router(router, prefix="/api")
        return app

    def test_ws_rejects_evil_host(self):
        client = TestClient(self._ws_app())
        with pytest.raises(Exception):  # starlette WebSocketDisconnect
            with client.websocket_connect("/api/ws", headers={"host": "evil.com:18989"}):
                pass

    def test_ws_rejects_evil_origin(self):
        client = TestClient(self._ws_app())
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/ws",
                headers={"host": "127.0.0.1:18989", "origin": "http://evil.com"},
            ):
                pass

    def test_ws_allows_no_origin_from_allowed_host(self):
        """Tauri 原生插件无 Origin、Host 白名单 → 允许连接。"""
        from backend.api.ws import manager

        client = TestClient(self._ws_app())
        # 规避共享轮询任务未启动导致的 receive 阻塞：连接后立即关闭
        with client.websocket_connect(
            "/api/ws", headers={"host": "127.0.0.1:18989"}
        ) as ws:
            assert ws.receive_json()["type"] == "connected"
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
        assert manager.active_count == 0  # 断开后已清理

    def test_ws_allows_whitelisted_origin(self):
        from backend.api.ws import manager

        client = TestClient(self._ws_app())
        with client.websocket_connect(
            "/api/ws",
            headers={"host": "127.0.0.1:18989", "origin": "http://tauri.localhost"},
        ) as ws:
            assert ws.receive_json()["type"] == "connected"
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
        assert manager.active_count == 0

    def test_ws_connection_cap(self, monkeypatch):
        """连接数达到上限后拒绝新连接（轻量 DoS 防护）。"""
        from backend.api.ws import manager

        client = TestClient(self._ws_app())

        # 造 16 个“已连接”占位，使 active_count 达到上限
        fakes = [object() for _ in range(16)]
        monkeypatch.setattr(manager, "_connections", list(fakes))
        assert manager.active_count == 16

        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/ws", headers={"host": "127.0.0.1:18989"}
            ):
                pass

        monkeypatch.setattr(manager, "_connections", [])