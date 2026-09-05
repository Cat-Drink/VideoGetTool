"""B 站（Bilibili）REST API。

暴露链接解析、用户主页抓取、播放流获取、Cookie 测试等接口。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.state import ctx
from app.crypto import decrypt_secret, encrypt_secret
from crawlers.bilibili.bili_http_client import BiliAPIError

router = APIRouter()

# 批量解析最大 URL 数量限制
MAX_PARSE_URLS: int = 50

# 批量解析并发上限（避免触发 B 站 -412 风控）
PARSE_CONCURRENCY_LIMIT: int = 5

# 用户主页抓取数量边界
MAX_SPACE_COUNT: int = 100


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
    type: str | None = None
    error: str | None = None


class BiliSpaceRequest(BaseModel):
    """B 站用户主页抓取请求。"""

    url: str
    mid: int | None = None
    max_count: int = Field(default=50, ge=1, le=100)


class BiliPlayUrlRequest(BaseModel):
    """B 站播放流请求。"""

    bvid: str
    cid: int
    quality: int = 80
    cookie: str | None = None
    # 未显式传 cookie 时，是否回退使用已保存的 B 站 Cookie（默认 True）
    use_saved_cookie: bool = True


class BiliStreamResponse(BaseModel):
    """B 站视频流响应。"""

    id: int
    url: str
    mime_type: str = ""
    codecs: str = ""
    width: int = 0
    height: int = 0
    bandwidth: int = 0


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

    cookie = req.bilibili_cookie or None

    async def _parse_one(url: str) -> BiliParseResult:
        try:
            parsed = await ctx.bili_url_parser.parse(url)
            if parsed.type == "video" and (parsed.bvid or parsed.av_id):
                try:
                    info = await ctx.bili_video_parser.parse_video(
                        bvid=parsed.bvid, aid=parsed.av_id, cookie=cookie
                    )
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
                        pages=[
                            BiliPageResponse(
                                cid=p.cid, page=p.page, title=p.title, duration=p.duration
                            )
                            for p in info.pages
                        ],
                        view_count=info.view_count,
                        danmaku_count=info.danmaku_count,
                        publish_time=info.pubdate,
                        tags=info.tags,
                        type="video",
                    )
                except Exception as e:
                    return BiliParseResult(
                        url=url,
                        bvid=parsed.bvid,
                        aid=parsed.av_id,
                        type="video",
                        error=f"视频信息获取失败: {e}",
                    )
            elif parsed.mid:
                return BiliParseResult(url=url, mid=parsed.mid, type="user_home")
            else:
                return BiliParseResult(
                    url=url, bvid=parsed.bvid, type="video", error="无法识别的链接类型"
                )
        except Exception as e:
            return BiliParseResult(url=url, error=str(e))

    # 并发受限（PARSE_CONCURRENCY_LIMIT），避免批量解析触发 B 站风控
    semaphore = asyncio.Semaphore(PARSE_CONCURRENCY_LIMIT)

    async def _limited(url: str) -> BiliParseResult:
        async with semaphore:
            return await _parse_one(url)

    tasks = [asyncio.create_task(_limited(url)) for url in req.urls]
    results = await asyncio.gather(*tasks)
    return results


@router.post("/playurl", response_model=BiliPlayUrlResult)
async def bili_playurl(req: BiliPlayUrlRequest):
    """获取 B 站视频播放流地址（DASH 格式）。

    需要 WBI 签名。高质量视频返回 DASH 格式（音视频分离），
    低质量视频可能返回单一 MP4 直链。

    Cookie 解析优先级：
        1. 请求显式传入的 cookie（req.cookie）
        2. 未传时回退到已保存的 B 站 Cookie（config.bilibili_cookie）
        3. 都没有 → 匿名请求（B 站通常只返回最高 720P）
    """
    if ctx.bili_video_parser is None:
        raise HTTPException(status_code=503, detail="B 站服务未初始化")

    cookie = req.cookie or None
    if not cookie and req.use_saved_cookie and ctx.config_repo is not None:
        # 审计 H3：已保存的 Cookie 为 DPAPI 密文，读取后解密再使用
        cookie = decrypt_secret(ctx.config_repo.get("bilibili_cookie") or "") or None

    try:
        playurl = await ctx.bili_video_parser.parse_playurl(
            bvid=req.bvid, cid=req.cid, quality=req.quality, cookie=cookie
        )
        return BiliPlayUrlResult(
            bvid=playurl.bvid,
            cid=playurl.cid,
            quality=playurl.quality,
            quality_name=playurl.quality_name,
            dash=playurl.dash,
            video_streams=[
                BiliStreamResponse(
                    id=s.id,
                    url=s.url,
                    mime_type=s.mime_type,
                    codecs=s.codecs,
                    width=s.width,
                    height=s.height,
                    bandwidth=s.bandwidth,
                )
                for s in playurl.video_streams
            ],
            audio_streams=[
                BiliStreamResponse(
                    id=s.id,
                    url=s.url,
                    mime_type=s.mime_type,
                    codecs=s.codecs,
                    bandwidth=s.bandwidth,
                )
                for s in playurl.audio_streams
            ],
            url=playurl.url,
            duration=playurl.duration,
        )
    except BiliAPIError as e:
        raise HTTPException(status_code=400, detail=f"B 站 API 错误: {e.message}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"播放流获取失败: {e}") from e


@router.post("/fetch-space", response_model=dict)
async def bili_fetch_space(req: BiliSpaceRequest):
    """抓取 B 站用户主页投稿列表。

    返回项与 BiliParseResult 契约一致（url / type / publish_time 等），
    has_more / total 基于接口真实总数判断。
    """
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

        # 复用已保存的 B 站 Cookie（与 /playurl 一致），支持受限用户主页抓取
        # 审计 H3：存储为 DPAPI 密文，读取后解密再使用
        cookie = decrypt_secret(ctx.config_repo.get("bilibili_cookie") or "") or None
        posts, has_more, total = await ctx.bili_user_crawler.fetch_user_posts_with_meta(
            mid, max_count=req.max_count, cookie=cookie
        )
        items = [
            {
                "url": f"https://www.bilibili.com/video/{post.bvid}",
                "type": "video",
                "bvid": post.bvid,
                "aid": post.aid,
                "title": post.title,
                "author": post.author,
                "cover_url": post.cover_url,
                "duration": post.duration,
                "view_count": post.view_count,
                "danmaku_count": post.danmaku_count,
                "publish_time": post.pubdate,
                "description": post.description,
            }
            for post in posts
        ]
        return {"items": items, "has_more": has_more, "total": total}
    except BiliAPIError as e:
        raise HTTPException(status_code=400, detail=f"B 站 API 错误: {e.message}") from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"主页抓取失败: {e}") from e


@router.post("/cookie-test", response_model=BiliCookieTestResult)
async def bili_cookie_test(req: BiliCookieTestRequest):
    """测试 B 站 Cookie 的有效性。

    Cookie 以每请求参数传入，不写入共享客户端，避免污染后续请求。
    """
    if ctx.bili_http_client is None or ctx.bili_signer is None:
        raise HTTPException(status_code=503, detail="B 站服务未初始化")

    from crawlers.bilibili.constants import NAV_URL

    try:
        # 先刷新 WBI 密钥（首次使用需要）
        await ctx.bili_signer.refresh_keys(ctx.bili_http_client.client)
        # 携带测试 Cookie 发起 nav 请求检测登录状态（仅本次请求生效）
        data = await ctx.bili_http_client.get_json(NAV_URL, signed=False, cookie=req.cookie)
        is_login = data.get("isLogin", False)
        # nav 响应的 uname 位于 data 顶层（get_json 已解包外层 data）；
        # 兼容个别嵌套形态（data.data.uname）与非 dict 响应
        if isinstance(data, dict):
            uname = data.get("uname") or (data.get("data") or {}).get("uname")
        else:
            uname = None
        return BiliCookieTestResult(
            valid=is_login,
            nickname=uname,
            message="" if is_login else "Cookie 未登录或已失效",
        )
    except BiliAPIError as e:
        return BiliCookieTestResult(valid=False, message=f"接口错误: {e.message}")
    except Exception as e:
        return BiliCookieTestResult(valid=False, message=f"测试失败: {e}")


# === B 站 Cookie 持久化管理 ===


class BiliCookieGetResponse(BaseModel):
    """B 站 Cookie 查询响应。"""

    has_cookie: bool
    # Cookie 前缀（仅显示前 4 位，用于确认已设置）
    cookie_prefix: str = ""
    # 上次测试状态（null 表示未测试过或已清除）
    last_valid: bool | None = None
    last_nickname: str | None = None


class BiliCookieSetRequest(BaseModel):
    """B 站 Cookie 设置请求。"""

    cookie: str
    # 保存后是否自动执行测试
    test: bool = True


@router.get("/cookie", response_model=BiliCookieGetResponse)
async def bili_get_cookie():
    """获取已保存的 B 站 Cookie 信息（不返回完整 Cookie）。"""
    if ctx.config_repo is None:
        raise HTTPException(status_code=503, detail="服务未初始化")
    # 审计 H3：存储为 DPAPI 密文；读取解密后取前缀展示（不返回完整 Cookie）
    saved = decrypt_secret(ctx.config_repo.get("bilibili_cookie") or "") or ""
    has = bool(saved)
    valid_str = ctx.config_repo.get("bilibili_cookie_valid") or ""
    last_valid = True if valid_str == "1" else False if valid_str == "0" else None
    nickname = ctx.config_repo.get("bilibili_cookie_nickname") or None
    return BiliCookieGetResponse(
        has_cookie=has,
        cookie_prefix=saved[:4] if has else "",
        last_valid=last_valid,
        last_nickname=nickname,
    )


class BiliCookieSetResponse(BaseModel):
    """B 站 Cookie 设置响应。"""

    saved: bool
    message: str = ""
    test_result: BiliCookieTestResult | None = None


@router.post("/cookie", response_model=BiliCookieSetResponse)
async def bili_set_cookie(req: BiliCookieSetRequest):
    """保存 B 站 Cookie 到本地配置，可选测试有效性。"""
    if ctx.config_repo is None:
        raise HTTPException(status_code=503, detail="服务未初始化")

    # 审计 H3：DPAPI 加密后再落库
    ctx.config_repo.set("bilibili_cookie", encrypt_secret(req.cookie.strip()))
    ctx.config_repo.set("bilibili_cookie_valid", "")
    ctx.config_repo.set("bilibili_cookie_nickname", "")

    test_result = None
    if req.test:
        # 复用 cookie-test 逻辑
        tester = BiliCookieTestRequest(cookie=req.cookie)
        test_result = await bili_cookie_test(tester)
        if test_result.valid:
            ctx.config_repo.set("bilibili_cookie_valid", "1")
            if test_result.nickname:
                ctx.config_repo.set("bilibili_cookie_nickname", test_result.nickname)
        else:
            ctx.config_repo.set("bilibili_cookie_valid", "0")

    return BiliCookieSetResponse(
        saved=True,
        message="Cookie 已保存",
        test_result=test_result,
    )


@router.delete("/cookie", response_model=dict)
async def bili_delete_cookie():
    """清除已保存的 B 站 Cookie。"""
    if ctx.config_repo is None:
        raise HTTPException(status_code=503, detail="服务未初始化")
    ctx.config_repo.delete("bilibili_cookie")
    ctx.config_repo.delete("bilibili_cookie_valid")
    ctx.config_repo.delete("bilibili_cookie_nickname")
    return {"message": "B 站 Cookie 已清除"}
