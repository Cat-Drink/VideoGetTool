"""本地 sidecar 安全中间件：Host 头守卫（DNS rebinding 防护）。

攻击模型：恶意网页通过 DNS rebinding 把 evil.com 解析到 127.0.0.1，
浏览器向 ``http://evil.com:18989`` 发请求，``Host`` 头为 ``evil.com:18989``。
CORS 只能阻止浏览器**读取**响应，不能阻止请求**发送**，因此必须在入口处
校验 Host 头（默认拒绝）。

本模块同时提供 HTTP 中间件（拦截普通请求）与纯函数（供 WebSocket
端点复用，因为 ``BaseHTTPMiddleware`` 不处理 WebSocket scope）。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 允许的 Host 头（大小写不敏感；带/不带端口均接受）
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "127.0.0.1",
        "127.0.0.1:18989",
        "localhost",
        "localhost:18989",
        "::1",
        "[::1]:18989",
    }
)


def is_host_allowed(host: str | None) -> bool:
    """Host 头准入判断。

    参数:
        host: 请求/握手头中的 Host 值；缺失（HTTP/1.0）返回 False。

    返回:
        属于白名单返回 True，否则 False。
    """
    return (host or "").strip().lower() in ALLOWED_HOSTS


class HostGuardMiddleware(BaseHTTPMiddleware):
    """拒绝 Host 头不在白名单内的 HTTP 请求（403）。"""

    async def dispatch(self, request: Request, call_next):
        if not is_host_allowed(request.headers.get("host")):
            return JSONResponse(status_code=403, content={"detail": "host not allowed"})
        return await call_next(request)
