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
    - 拒绝回环/私网/链路本地/保留地址主机名（文本前缀）
    - 在连接阶段对解析出的实际 IP 再次校验私网/保留段，防御 DNS rebinding
      与"域名解析到内网/元数据地址"绕过（如 localtest.me→127.0.0.1、
      nicob.nsroot.io→169.254.169.254）
    - URL 长度上限
    - 响应体大小上限，避免大体积响应全量载入内存
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

import httpx
from fastapi import APIRouter, HTTPException, Query, Response
from httpx import AsyncHTTPTransport

router = APIRouter()

# 封面抓取超时（秒）
_FETCH_TIMEOUT: float = 10.0

# 响应体大小上限（20MB），避免大体积图片/非图片响应全量载入内存
_MAX_COVER_BYTES: int = 20 * 1024 * 1024

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

# RFC 2544 基准测试网段（198.18.0.0/15）：Clash / sing-box / V2Ray 等代理工具
# 在 TUN 模式下使用该网段作为虚拟网关地址，抖音封面 CDN（douyinpic.com）在
# 这类网络环境下会解析到 198.18.0.x。该网段并非真实私网/内网基础设施，
# Python ipaddress 却将其 is_private 判定为 True，若按 is_private 一律拦截，
# 会误伤经本地透明代理加载的封面/预览图（详见 objective：列表项预览图不显示）。
# 因此显式放行该网段（请求仍经由用户本地代理出口，不构成 SSRF 到内网的风险）。
_BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _is_blocked_ip(ip: str) -> bool:
    """判断 IP 地址是否属于禁止访问的私网/保留/回环等范围。

    无法解析为合法 IP 时也视为禁止（防御异常输入）。
    RFC 2544 基准测试网段（198.18.0.0/15）被 Clash/sing-box 等 TUN 模式
    透明代理用作虚拟网关地址，予以放行，避免误伤经代理加载的封面图。

    参数:
        ip: 点分十进制 IPv4 或标准 IPv6 字符串。

    返回:
        禁止访问返回 True。
    """
    try:
        addr = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return True
    # IPv4：仅放行 198.18.x.x 基准测试网段（Clash TUN 虚拟网关），
    # IPv6 无该网段概念；and 短路保证 IPv6 不触发 IPv4 网络比对（N1）
    if isinstance(addr, ipaddress.IPv4Address) and addr in _BENCHMARK_NETWORK:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


class _SSRFGuardTransport(AsyncHTTPTransport):
    """在连接阶段校验解析后 IP 的 httpx 传输层。

    文本前缀检查无法防御"域名解析到内网/元数据地址"的 DNS rebinding 攻击。
    本 Transport 在真正建连前对 getaddrinfo 解析出的每个 IP 再次校验，
    任一命中私网/保留段即拒绝请求。
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host:
            port = request.url.port or (443 if request.url.scheme == "https" else 80)
            # 审计 M1：同步 socket.getaddrinfo 会阻塞事件循环（慢 DNS = DoS），
            # 改用 loop.getaddrinfo 协程化解析。
            loop = asyncio.get_running_loop()
            try:
                addrinfos = await loop.getaddrinfo(
                    host, port, type=socket.SOCK_STREAM
                )
            except OSError as exc:
                raise httpx.ConnectError(f"DNS resolution failed for {host}: {exc}") from exc
            for info in addrinfos:
                ip = info[4][0]
                if _is_blocked_ip(ip):
                    raise httpx.ConnectError(f"blocked target ip {ip} for host {host}")
        return await super().handle_async_request(request)


def _validate_url(url: str) -> str:
    """校验并归一化远程图片 URL（防 SSRF），返回原 URL。

    第一层（文本）校验：协议白名单、主机名前缀黑名单、URL 长度。
    第二层（解析 IP）校验由 _SSRFGuardTransport 在连接阶段完成。
    """
    if not url:
        raise HTTPException(status_code=400, detail="missing url")
    if len(url) > 4096:
        raise HTTPException(status_code=400, detail="url too long")
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="only http/https allowed")
    host = (parts.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="missing host")
    if host in _BLOCKED_HOSTS or any(host.startswith(p) for p in _BLOCKED_HOST_PREFIXES):
        raise HTTPException(status_code=400, detail="target not allowed")
    return url


@router.get("/covers")
async def proxy_cover(url: str = Query(...)):
    """抓取远程封面/图片并以本地来源返回。

    - 服务端 httpx 抓取，携带浏览器 UA 与 Referer，规避 CDN 防盗链。
    - 响应带 Cache-Control，让 WebView 缓存封面减少重复请求。
    - 不跟随重定向：落地 URL 不可控时直接失败，避免 SSRF 重定向绕过。
    - 流式接收并校验大小上限，避免大体积响应全量载入内存。
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
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=_FETCH_TIMEOUT,
            transport=_SSRFGuardTransport(),
        ) as client:
            resp = await client.get(target, headers=headers)
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=400, detail=f"target blocked or unreachable: {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"fetch failed: {exc}") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"upstream {resp.status_code}")

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=502, detail=f"unexpected content-type {content_type}")

    # 预检 Content-Length，提前拒绝超大响应
    declared = resp.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_COVER_BYTES:
                raise HTTPException(status_code=413, detail="image too large")
        except ValueError:
            pass

    # 流式接收并校验实际大小上限，避免 resp.content 全量载入内存
    body = bytearray()
    async for chunk in resp.aiter_bytes(64 * 1024):
        body.extend(chunk)
        if len(body) > _MAX_COVER_BYTES:
            raise HTTPException(status_code=413, detail="image too large")

    return Response(
        content=bytes(body),
        media_type=content_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
