"""爬虫/解析 REST API。

暴露链接解析、主页抓取、预览等接口。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import now_iso
from backend.state import ctx
from crawlers.user_home_crawler import HomeFilters

router = APIRouter()


# === 请求/响应模型 ===


class ParseRequest(BaseModel):
    """解析请求。"""

    urls: list[str]
    task_id: int | None = None


class ParsedURLResponse(BaseModel):
    """解析结果响应。"""

    url: str
    title: str | None = None
    author: str | None = None
    type: str = "video"
    aweme_id: str | None = None
    cover_url: str | None = None
    duration: str | None = None
    image_count: int | None = None
    no_watermark_url: str | None = None
    image_urls: list[str] | None = None
    item_video_urls: list[str] | None = None
    publish_time: str | None = None
    error: str | None = None


class FetchHomeRequest(BaseModel):
    """主页抓取请求。"""

    url: str
    max_items: int = 30
    offset: int = 0


class FetchHomeResponse(BaseModel):
    """主页抓取结果。"""

    items: list[ParsedURLResponse]
    has_more: bool = False
    total: int | None = None


# === API 端点 ===


@router.post("/parse", response_model=list[ParsedURLResponse])
async def parse_urls(req: ParseRequest):
    """解析抖音链接列表，返回解析结果。

    对每个链接做两步：
    1. URLParser.parse() 提取 aweme_id / sec_user_id
    2. VideoParser.parse() 调用 detail 接口获取完整信息（标题、封面、类型等）
    """
    if ctx.url_parser is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 获取一个有效 Cookie
    cookie = ""
    if ctx.cookie_repo is not None:
        valid_cookie = ctx.cookie_repo.get_valid()
        if valid_cookie is not None:
            cookie = valid_cookie.content
            ctx.cookie_repo.update_last_used(valid_cookie.id, now_iso())

    results = []
    for url in req.urls:
        try:
            # Step 1: 解析 URL 提取 aweme_id
            parsed_url = await ctx.url_parser.parse(url)
            aweme_id = parsed_url.aweme_id

            # Step 2: 如果是视频/图集，用 VideoParser 获取详细信息
            if aweme_id and ctx.video_parser is not None:
                try:
                    video_info = await ctx.video_parser.parse_video(aweme_id, cookie)
                    results.append(
                        ParsedURLResponse(
                            url=url,
                            title=video_info.title,
                            author=video_info.author,
                            type=video_info.type,
                            aweme_id=aweme_id,
                            cover_url=video_info.cover_url,
                            duration=video_info.duration,
                            image_count=(
                                len(video_info.image_urls) if video_info.image_urls else None
                            ),
                            no_watermark_url=video_info.no_watermark_url,
                            image_urls=video_info.image_urls or None,
                            item_video_urls=video_info.item_video_urls or None,
                            publish_time=video_info.publish_time,
                        )
                    )
                except Exception as ve:
                    # VideoParser 失败，回退到基本解析信息
                    error_msg = f"视频详情解析失败: {ve}"
                    # 对 vsdetail 直播回放链接，提示可能需灯牌等级
                    if "/vsdetail/" in url:
                        error_msg += "（直播回放可能需要粉丝灯牌等级）"
                    results.append(
                        ParsedURLResponse(
                            url=url,
                            type=parsed_url.type,
                            aweme_id=aweme_id,
                            error=error_msg,
                        )
                    )
            else:
                # 主页链接或其他类型
                results.append(
                    ParsedURLResponse(
                        url=url,
                        type=parsed_url.type,
                        aweme_id=aweme_id,
                    )
                )
        except Exception as e:
            results.append(
                ParsedURLResponse(
                    url=url,
                    error=str(e),
                )
            )
    return results


@router.post("/fetch-home", response_model=FetchHomeResponse)
async def fetch_home(req: FetchHomeRequest):
    """抓取用户主页作品列表。"""
    if ctx.user_home_crawler is None or ctx.url_parser is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        # 1. 从 URL 解析 sec_user_id
        parsed_url = await ctx.url_parser.parse(req.url)
        if parsed_url.type != "user_home" or not parsed_url.sec_user_id:
            raise HTTPException(status_code=400, detail="无法从 URL 解析用户主页 ID")

        sec_user_id = parsed_url.sec_user_id

        # 2. 构造过滤条件
        filters = HomeFilters(
            type_filter="all",
            max_count=req.max_items,
        )

        # 3. 获取一个有效 Cookie
        cookie = ""
        if ctx.cookie_repo is not None:
            valid_cookie = ctx.cookie_repo.get_valid()
            if valid_cookie is not None:
                cookie = valid_cookie.content

        # 4. 消费异步迭代器
        items = []
        async for post in ctx.user_home_crawler.fetch_user_posts(sec_user_id, filters, cookie):
            items.append(
                ParsedURLResponse(
                    url=f"https://www.douyin.com/video/{post.aweme_id}",
                    title=post.title,
                    author=post.author,
                    type=post.type,
                    aweme_id=post.aweme_id,
                    cover_url=post.cover_url,
                    duration=post.duration,
                    image_count=post.image_count,
                    publish_time=post.create_time,
                )
            )
            if len(items) >= req.max_items:
                break

        return FetchHomeResponse(
            items=items,
            has_more=len(items) >= req.max_items,
            total=len(items),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/preview", response_model=ParsedURLResponse)
async def preview_url(url: str):
    """预览单个链接（快速解析，返回基本信息）。"""
    if ctx.url_parser is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 获取一个有效 Cookie
    cookie = ""
    if ctx.cookie_repo is not None:
        valid_cookie = ctx.cookie_repo.get_valid()
        if valid_cookie is not None:
            cookie = valid_cookie.content
            ctx.cookie_repo.update_last_used(valid_cookie.id, now_iso())

    try:
        parsed_url = await ctx.url_parser.parse(url)
        aweme_id = parsed_url.aweme_id

        if aweme_id and ctx.video_parser is not None:
            try:
                video_info = await ctx.video_parser.parse_video(aweme_id, cookie)
                return ParsedURLResponse(
                    url=url,
                    title=video_info.title,
                    author=video_info.author,
                    type=video_info.type,
                    aweme_id=aweme_id,
                    cover_url=video_info.cover_url,
                    duration=video_info.duration,
                    image_count=len(video_info.image_urls) if video_info.image_urls else None,
                    no_watermark_url=video_info.no_watermark_url,
                    image_urls=video_info.image_urls or None,
                    item_video_urls=video_info.item_video_urls or None,
                    publish_time=video_info.publish_time,
                )
            except Exception as ve:
                return ParsedURLResponse(
                    url=url,
                    type=parsed_url.type,
                    aweme_id=aweme_id,
                    error=str(ve),
                )

        return ParsedURLResponse(url=url, type=parsed_url.type, aweme_id=aweme_id)
    except Exception as e:
        return ParsedURLResponse(url=url, error=str(e))
