"""B 站（Bilibili）REST API。

暴露链接解析、用户主页抓取、播放流获取、Cookie 测试等接口。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.state import ctx
from crawlers.bilibili.bili_http_client import BiliAPIError

router = APIRouter()

# 批量解析最大 URL 数量限制
MAX_PARSE_URLS: int = 50


# === 请求/响应模型 ===


class BiliParseRequest(BaseModel):
    """B 站解析请求。"""

    urls: list[str]
    bilibili_cookie: str | None = None


class BiliPageResponse(BaseModel):
    """B 站分 P 信息。"""

    cid: int
    page: int
    title: str
    duration: int


class BiliParseResult(BaseModel):
    """B 站解析结果项。"""

    url: str
    bvid: str | None = None
    aid: int | None = None
    title: str | None = None
    author: str | None = None
    author_mid: int | None = None
    cover_url: str | None = None
    duration: int | None = None
    description: str | None = None
    pages: list[BiliPageResponse] | None = None
    view_count: int | None = None
    danmaku_count: int | None = None
    publish_time: int | None = None
    tags: list[str] | None = None
    mid: int | None = None
    error: str | None = None


class BiliSpaceRequest(BaseModel):
    """B 站用户主页抓取请求。"""

    url: str
    mid: int | None = None
    max_count: int = 50


class BiliPlayUrlRequest(BaseModel):
    """B 站播放流请求。"""

    bvid: str
    cid: int
    quality: int = 80


class BiliStreamResponse(BaseModel):
    """B 站视频流响应。"""

    id: int
    url: str
    mime_type: str = ""
    codecs: str = ""
    width: int = 0
    height: int = 0


class BiliPlayUrlResult(BaseModel):
    """B 站播放流响应。"""

    bvid: str
    cid: int
    quality: int
    quality_name: str
    dash: bool = True
    video_streams: list[BiliStreamResponse] = []
    audio_streams: list[BiliStreamResponse] = []
    url: str = ""
    duration: int = 0


class BiliCookieTestRequest(BaseModel):
    """B 站 Cookie 测试请求。"""

    cookie: str


class BiliCookieTestResult(BaseModel):
    """B 站 Cookie 测试结果。"""

    valid: bool
    nickname: str | None = None
    message: str = ""


# === API 端点 ===


@router.post("/parse", response_model=list[BiliParseResult])
async def bili_parse_urls(req: BiliParseRequest):
    """解析 B 站链接列表，返回视频基本信息。

    对每个链接做两步：
    1. BiliURLParser 解析类型与 bvid/mid
    2. BiliVideoParser 调用 VIEW 接口获取视频信息
    """
    if ctx.bili_url_parser is None or ctx.bili_video_parser is None:
        raise HTTPException(status_code=503, detail="B 站服务未初始化")

    if len(req.urls) > MAX_PARSE_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"批量解析最多 {MAX_PARSE_URLS} 个链接，当前 {len(req.urls)} 个",
        )

    # 设置 Cookie（如果有）
    if req.bilibili_cookie and ctx.bili_http_client is not None:
        ctx.bili_http_client.set_cookie(req.bilibili_cookie)

    async def _parse_one(url: str) -> BiliParseResult:
        try:
            parsed = await ctx.bili_url_parser.parse(url)
            if parsed.type == "video" and parsed.bvid:
                try:
                    info = await ctx.bili_video_parser.parse_video(bvid=parsed.bvid)
                    return BiliParseResult(
                        url=url,
                        bvid=info.bvid,
                        aid=info.aid,
                        title=info.title,
                        author=info.author,
                        author_mid=info.author_mid,
                        cover_url=info.cover_url,
                        duration=info.duration,
                        description=info.description,
                        pages=[BiliPageResponse(cid=p.cid, page=p.page, title=p.title, duration=p.duration) for p in info.pages],
                        view_count=info.view_count,
                        danmaku_count=info.danmaku_count,
                        publish_time=info.pubdate,
                        tags=info.tags,
                    )
                except Exception as e:
                    return BiliParseResult(url=url, bvid=parsed.bvid, error=f"视频信息获取失败: {e}")
            elif parsed.mid:
                return BiliParseResult(url=url, mid=parsed.mid)
            else:
                return BiliParseResult(url=url, bvid=parsed.bvid, error="无法识别的链接类型")
        except Exception as e:
            return BiliParseResult(url=url, error=str(e))

    import asyncio
    tasks = [asyncio.create_task(_parse_one(url)) for url in req.urls]
    results = await asyncio.gather(*tasks)
    return results


@router.post("/playurl", response_model=BiliPlayUrlResult)
async def bili_playurl(req: BiliPlayUrlRequest):
    """获取 B 站视频播放流地址（DASH 格式）。

    需要 WBI 签名。高质量视频返回 DASH 格式（音视频分离），
    低质量视频可能返回单一 MP4 直链。
    """
    if ctx.bili_video_parser is None:
        raise HTTPException(status_code=503, detail="B 站服务未初始化")

    try:
        playurl = await ctx.bili_video_parser.parse_playurl(
            bvid=req.bvid, cid=req.cid, quality=req.quality
        )
        return BiliPlayUrlResult(
            bvid=playurl.bvid,
            cid=playurl.cid,
            quality=playurl.quality,
            quality_name=playurl.quality_name,
            dash=playurl.dash,
            video_streams=[
                BiliStreamResponse(id=s.id, url=s.url, mime_type=s.mime_type, codecs=s.codecs, width=s.width, height=s.height)
                for s in playurl.video_streams
            ],
            audio_streams=[
                BiliStreamResponse(id=s.id, url=s.url, mime_type=s.mime_type, codecs=s.codecs)
                for s in playurl.audio_streams
            ],
            url=playurl.url,
            duration=playurl.duration,
        )
    except BiliAPIError as e:
        raise HTTPException(status_code=400, detail=f"B 站 API 错误: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"播放流获取失败: {e}")


@router.post("/fetch-space", response_model=dict)
async def bili_fetch_space(req: BiliSpaceRequest):
    """抓取 B 站用户主页投稿列表。"""
    if ctx.bili_user_crawler is None or ctx.bili_url_parser is None:
        raise HTTPException(status_code=503, detail="B 站服务未初始化")

    try:
        # 从 URL 解析 mid
        mid = req.mid
        if mid is None:
            parsed = await ctx.bili_url_parser.parse(req.url)
            if parsed.mid:
                mid = parsed.mid
            else:
                raise HTTPException(status_code=400, detail="无法从 URL 解析用户 ID")

        items = []
        async for post in ctx.bili_user_crawler.fetch_user_posts(mid, max_count=req.max_count):
            items.append({
                "bvid": post.bvid,
                "aid": post.aid,
                "title": post.title,
                "author": post.author,
                "cover_url": post.cover_url,
                "duration": post.duration,
                "view_count": post.view_count,
                "danmaku_count": post.danmaku_count,
                "pubdate": post.pubdate,
                "description": post.description,
            })
        return {"items": items, "has_more": len(items) >= req.max_count}
    except BiliAPIError as e:
        raise HTTPException(status_code=400, detail=f"B 站 API 错误: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"主页抓取失败: {e}")


@router.post("/cookie-test", response_model=BiliCookieTestResult)
async def bili_cookie_test(req: BiliCookieTestRequest):
    """测试 B 站 Cookie 的有效性。"""
    if ctx.bili_http_client is None or ctx.bili_signer is None:
        raise HTTPException(status_code=503, detail="B 站服务未初始化")

    from crawlers.bilibili.constants import NAV_URL

    try:
        # 先刷新 WBI 密钥（首次使用需要）
        await ctx.bili_signer.refresh_keys(ctx.bili_http_client._client)
        # 设置 Cookie 并发起 nav 请求检测登录状态
        ctx.bili_http_client.set_cookie(req.cookie)
        data = await ctx.bili_http_client.get_json(NAV_URL, signed=False)
        is_login = data.get("isLogin", False)
        uname = data.get("uname") or data.get("Uname") or (data.get("data") or {}).get("uname") if isinstance(data, dict) else None
        return BiliCookieTestResult(
            valid=is_login,
            nickname=uname,
            message="" if is_login else "Cookie 未登录或已失效",
        )
    except BiliAPIError as e:
        return BiliCookieTestResult(valid=False, message=f"接口错误: {e.message}")
    except Exception as e:
        return BiliCookieTestResult(valid=False, message=f"测试失败: {e}")
