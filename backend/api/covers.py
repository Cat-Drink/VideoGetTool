"""封面/预览图代理接口。

问题背景：
    Tauri 2 打包后，前端运行在自定义协议页面（http://tauri.localhost），
    直接以 <img> 加载远程 http/https 图片时，可能被 WebView 的混合内容
    规则或子资源网络策略拦截，导致封面/预览图不渲染（实测 http→https
    归一化无法解决）。而前端对本地 sidecar（http://127.0.0.1:18989）
    的请求始终可用。

方案：
    由本地 sidecar 在服务端抓取远程图片，再以 127.0.0.1 来源返回给前端，
    <img> 指向本地地址即可稳定渲染，同时规避 CDN 防盗链（服务端携带
    UA/Referer）。

安全（防 SSRF）：
    - 仅允许 http/https 协议
    - 拒绝回环/私网/链路本地/保留地址主机名
    - URL 长度上限
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

router = APIRouter()

# 封面抓取超时（秒）
_FETCH_TIMEOUT: float = 10.0

# 拒绝的主机名（防 SSRF）：回环、私网、链路本地、保留、IPv6 回环等
_BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "169.254.169.254",
}
_BLOCKED_HOST_PREFIXES = (
    "127.",
    "10.",
    "192.168.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
    "169.254.",
    "0.",
    "::1",
    "::ffff:",
    "fe80:",
    "fc",
    "fd",
)

# 允许返回的图片 Content-Type
_ALLOWED_CONTENT_TYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
    "image/bmp",
)


def _validate_url(url: str) -> str:
    """校验并归一化远程图片 URL（防 SSRF），返回原 URL。"""
    if not url:
        raise HTTPException(status_code=400, detail="missing url")
    if len(url) > 4096:
        raise HTTPException(status_code=400, detail="url too long")
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="only http/https allowed")
    host = (parts.hostname or "").lower()
    if host in _BLOCKED_HOSTS or any(host.startswith(p) for p in _BLOCKED_HOST_PREFIXES):
        raise HTTPException(status_code=400, detail="target not allowed")
    return url


@router.get("/covers")
async def proxy_cover(url: str = Query(...)):
    """抓取远程封面/图片并以本地来源返回。

    - 服务端 httpx 抓取，携带浏览器 UA 与 Referer，规避 CDN 防盗链。
    - 响应带 Cache-Control，让 WebView 缓存封面减少重复请求。
    """
    target = _validate_url(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_FETCH_TIMEOUT) as client:
            resp = await client.get(target, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"fetch failed: {exc}") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"upstream {resp.status_code}")

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=502, detail=f"unexpected content-type {content_type}")

    return Response(
        content=resp.content,
        media_type=content_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
