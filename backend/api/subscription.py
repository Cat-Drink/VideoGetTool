"""订阅模式 REST API（v0.4.1）。

暴露订阅的增删改查、立即扫描、订阅作品处理（下载/跳过）等接口。
前端在「主页抓取」页面的「订阅模式」标签下调用。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import (
    Subscription,
    SubscriptionItem,
    SubscriptionItemStatus,
)
from backend.state import ctx

router = APIRouter()

# 订阅间隔允许范围（分钟）
MIN_INTERVAL_MINUTES: int = 5
MAX_INTERVAL_MINUTES: int = 24 * 60  # 1 天


# === 请求/响应模型 ===


class SubscriptionCreateRequest(BaseModel):
    """创建订阅请求。"""

    url: str
    name: str = ""
    interval_minutes: int = 30
    max_items: int = 30


class SubscriptionUpdateRequest(BaseModel):
    """更新订阅请求（仅更新非 None 字段）。"""

    name: str | None = None
    interval_minutes: int | None = None
    max_items: int | None = None
    enabled: int | None = None


class SubscriptionResponse(BaseModel):
    """订阅响应。"""

    id: int
    url: str
    sec_user_id: str
    name: str
    interval_minutes: int
    enabled: int
    max_items: int
    last_scan_at: str | None
    last_scan_status: str
    last_scan_error: str | None
    new_count: int = 0
    created_at: str
    updated_at: str


class SubscriptionItemResponse(BaseModel):
    """订阅作品响应。"""

    id: int
    subscription_id: int
    aweme_id: str
    url: str
    title: str | None
    author: str | None
    type: str
    duration: str | None
    image_count: int | None
    cover_url: str | None
    publish_time: str | None
    status: str
    created_at: str
    updated_at: str


class ScanResponse(BaseModel):
    """扫描结果响应。"""

    subscription_id: int
    new_count: int
    scanned_items: int
    status: str
    error: str | None = None


# === 内部辅助 ===


def _subscription_response(sub: Subscription, new_count: int = 0) -> SubscriptionResponse:
    """Subscription → SubscriptionResponse。"""
    return SubscriptionResponse(
        id=sub.id if sub.id is not None else 0,
        url=sub.url,
        sec_user_id=sub.sec_user_id,
        name=sub.name or "",
        interval_minutes=sub.interval_minutes,
        enabled=sub.enabled,
        max_items=sub.max_items,
        last_scan_at=sub.last_scan_at,
        last_scan_status=sub.last_scan_status or "",
        last_scan_error=sub.last_scan_error,
        new_count=new_count,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )


def _item_response(item: SubscriptionItem) -> SubscriptionItemResponse:
    """SubscriptionItem → SubscriptionItemResponse。"""
    return SubscriptionItemResponse(
        id=item.id if item.id is not None else 0,
        subscription_id=item.subscription_id,
        aweme_id=item.aweme_id,
        url=item.url,
        title=item.title,
        author=item.author,
        type=item.type,
        duration=item.duration,
        image_count=item.image_count,
        cover_url=item.cover_url,
        publish_time=item.publish_time,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


# === API 端点 ===


@router.get("/list", response_model=list[SubscriptionResponse])
async def list_subscriptions():
    """获取所有订阅（含各订阅新作品数量）。"""
    if ctx.subscription_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    subs = ctx.subscription_repo.get_all()
    new_counts = ctx.subscription_repo.count_new_items_map()
    return [_subscription_response(sub, new_counts.get(sub.id or 0, 0)) for sub in subs]


@router.post("/add", response_model=SubscriptionResponse)
async def add_subscription(req: SubscriptionCreateRequest):
    """添加订阅（解析 URL 得到 sec_user_id，重复订阅返回 409）。"""
    if ctx.subscription_repo is None or ctx.url_parser is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 校验间隔
    interval = req.interval_minutes
    if interval < MIN_INTERVAL_MINUTES or interval > MAX_INTERVAL_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"扫描间隔需在 {MIN_INTERVAL_MINUTES}–{MAX_INTERVAL_MINUTES} 分钟之间",
        )

    # 解析 URL → sec_user_id
    try:
        parsed = await ctx.url_parser.parse(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解析链接: {e}") from e
    if parsed.type != "user_home" or not parsed.sec_user_id:
        raise HTTPException(status_code=400, detail="链接不是抖音用户主页，无法订阅")

    # 去重
    if ctx.subscription_repo.exists_sec_user_id(parsed.sec_user_id):
        raise HTTPException(status_code=409, detail="该用户主页已订阅")

    sub = Subscription(
        id=None,
        url=req.url,
        sec_user_id=parsed.sec_user_id,
        name=req.name or "",
        interval_minutes=interval,
        enabled=1,
        max_items=max(1, min(req.max_items, 200)),
    )
    sub_id = ctx.subscription_repo.create(sub)
    created = ctx.subscription_repo.get(sub_id)
    if created is None:
        raise HTTPException(status_code=500, detail="订阅创建失败")
    return _subscription_response(created)


@router.post("/{sub_id}/update", response_model=SubscriptionResponse)
async def update_subscription(sub_id: int, req: SubscriptionUpdateRequest):
    """更新订阅（名称/间隔/启用状态/单次最大检查数）。"""
    if ctx.subscription_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    sub = ctx.subscription_repo.get(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")

    if req.interval_minutes is not None and (
        req.interval_minutes < MIN_INTERVAL_MINUTES or req.interval_minutes > MAX_INTERVAL_MINUTES
    ):
        raise HTTPException(
            status_code=400,
            detail=f"扫描间隔需在 {MIN_INTERVAL_MINUTES}–{MAX_INTERVAL_MINUTES} 分钟之间",
        )
    if req.enabled is not None and req.enabled not in (0, 1):
        raise HTTPException(status_code=400, detail="enabled 仅可为 0 或 1")

    ctx.subscription_repo.update(
        sub_id,
        name=req.name,
        interval_minutes=req.interval_minutes,
        max_items=req.max_items,
        enabled=req.enabled,
    )
    updated = ctx.subscription_repo.get(sub_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="订阅更新失败")
    new_count = ctx.subscription_repo.count_new_items(sub_id)
    return _subscription_response(updated, new_count)


@router.delete("/{sub_id}")
async def delete_subscription(sub_id: int):
    """删除订阅（级联删除其全部作品记录）。"""
    if ctx.subscription_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    sub = ctx.subscription_repo.get(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    ctx.subscription_repo.delete(sub_id)
    return {"message": f"订阅 {sub_id} 已删除"}


@router.post("/{sub_id}/scan", response_model=ScanResponse)
async def scan_subscription_now(sub_id: int):
    """立即扫描指定订阅，检测新作品。"""
    if ctx.subscription_repo is None or ctx.subscription_scanner is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    sub = ctx.subscription_repo.get(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    result = await ctx.subscription_scanner.scan_subscription(sub_id)
    return ScanResponse(
        subscription_id=result.subscription_id,
        new_count=result.new_count,
        scanned_items=result.scanned_items,
        status=result.status,
        error=result.error,
    )


@router.get("/{sub_id}/items", response_model=list[SubscriptionItemResponse])
async def list_subscription_items(sub_id: int, status: str | None = None):
    """获取订阅的作品列表，可按状态过滤（如 ?status=new）。"""
    if ctx.subscription_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    sub = ctx.subscription_repo.get(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if status is not None and status not in (
        SubscriptionItemStatus.NEW.value,
        SubscriptionItemStatus.ACCEPTED.value,
        SubscriptionItemStatus.SKIPPED.value,
    ):
        raise HTTPException(status_code=400, detail="状态参数非法")
    items = ctx.subscription_repo.get_items(sub_id, status=status, limit=200)
    return [_item_response(item) for item in items]


@router.post("/items/{item_id}/accept")
async def accept_subscription_item(item_id: int):
    """接受订阅作品：解析详情并入队下载，标记为已接受。

    复用 /api/download/start 的入队逻辑：创建 Task（source_type='subscription'），
    将作品信息（含 aweme_id）作为 items 传入，由下载流程完成详情解析与直链获取。
    """
    if ctx.subscription_repo is None or ctx.scheduler is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    item = ctx.subscription_repo.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="订阅作品不存在")
    if item.status != SubscriptionItemStatus.NEW.value:
        raise HTTPException(status_code=400, detail="该作品已被处理")

    # 复用下载入队逻辑
    from backend.api.download import enqueue_download_items

    task_id = await enqueue_download_items(
        source_type="subscription",
        source_url=item.url,
        items=[
            {
                "url": item.url,
                "title": item.title,
                "author": item.author,
                "type": item.type,
                "aweme_id": item.aweme_id,
                "cover_url": item.cover_url,
                "image_count": item.image_count,
            }
        ],
        download_dir=None,
    )
    ctx.subscription_repo.update_item_status(item_id, SubscriptionItemStatus.ACCEPTED.value)
    return {"message": "已入队下载", "task_id": task_id, "item_id": item_id}


@router.post("/items/{item_id}/skip")
async def skip_subscription_item(item_id: int):
    """跳过订阅作品（用户选择不下载）。"""
    if ctx.subscription_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    item = ctx.subscription_repo.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="订阅作品不存在")
    ctx.subscription_repo.update_item_status(item_id, SubscriptionItemStatus.SKIPPED.value)
    return {"message": "已跳过", "item_id": item_id}


@router.post("/{sub_id}/items/skip-all-new")
async def skip_all_new_items(sub_id: int):
    """跳过某订阅的所有新作品（一键清理）。"""
    if ctx.subscription_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    sub = ctx.subscription_repo.get(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    count = ctx.subscription_repo.update_items_status(
        sub_id,
        from_status=SubscriptionItemStatus.NEW.value,
        to_status=SubscriptionItemStatus.SKIPPED.value,
    )
    return {"message": f"已跳过 {count} 个作品", "count": count}


@router.post("/{sub_id}/scan-and-collect")
async def scan_and_collect(sub_id: int):
    """立即扫描并将全部新作品入队下载（便捷操作）。

    返回入队数量；跳过解析失败的单个作品不影响整体。
    """
    if ctx.subscription_repo is None or ctx.subscription_scanner is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    sub = ctx.subscription_repo.get(sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")

    result = await ctx.subscription_scanner.scan_subscription(sub_id)
    new_items = ctx.subscription_repo.get_new_items(sub_id)
    if not new_items:
        return {"message": "没有新作品", "queued": 0}

    from backend.api.download import enqueue_download_items

    items_payload = [
        {
            "url": it.url,
            "title": it.title,
            "author": it.author,
            "type": it.type,
            "aweme_id": it.aweme_id,
            "cover_url": it.cover_url,
            "image_count": it.image_count,
        }
        for it in new_items
    ]
    task_id = await enqueue_download_items(
        source_type="subscription",
        source_url=sub.url,
        items=items_payload,
        download_dir=None,
    )
    # 入队后全部标记为已接受；入队抛异常时保持 new 以便重试
    for it in new_items:
        if it.id is not None:
            ctx.subscription_repo.update_item_status(it.id, SubscriptionItemStatus.ACCEPTED.value)
    return {
        "message": f"已入队 {len(new_items)} 个新作品",
        "queued": len(new_items),
        "task_id": task_id,
        "scan_status": result.status,
        "scan_error": result.error,
    }
