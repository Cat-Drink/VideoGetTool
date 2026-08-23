"""下载任务 REST API。

暴露任务列表、启动下载、暂停/恢复/重试、清除已完成等接口。
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import Task, TaskItem, TaskItemStatus, TaskStatus, now_iso
from backend.state import ctx

router = APIRouter()
logger = logging.getLogger(__name__)


# === 请求/响应模型 ===


class StartDownloadRequest(BaseModel):
    """启动下载请求。"""

    source_type: str = "single"
    source_url: str | None = None
    items: list[dict] | None = None  # 批量下载时传入解析后的 items
    download_dir: str | None = None


class TaskResponse(BaseModel):
    """任务列表响应项。"""

    id: int
    source_type: str
    source_url: str | None
    status: str
    total_items: int
    completed_items: int
    created_at: str
    updated_at: str
    download_dir: str


class TaskItemResponse(BaseModel):
    """任务项响应。"""

    id: int | None
    task_id: int
    aweme_id: str | None
    url: str
    title: str | None
    author: str | None
    type: str
    status: str
    downloaded_bytes: int
    total_bytes: int
    progress: float = 0.0
    cover_url: str | None = None
    fail_reason: str | None
    local_path: str | None


# === API 端点 ===


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks():
    """获取所有下载任务列表。"""
    if ctx.task_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    tasks = ctx.task_repo.get_all()
    return [
        TaskResponse(
            id=task.id,
            source_type=task.source_type,
            source_url=task.source_url,
            status=task.status,
            total_items=task.total_items,
            completed_items=task.completed_items,
            created_at=task.created_at,
            updated_at=task.updated_at,
            download_dir=task.download_dir,
        )
        for task in tasks
    ]


@router.get("/tasks/{task_id}/items", response_model=list[TaskItemResponse])
async def list_task_items(task_id: int):
    """获取指定任务的下载项列表。"""
    if ctx.task_item_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    items = ctx.task_item_repo.get_by_task(task_id)
    return [
        TaskItemResponse(
            id=item.id,
            task_id=item.task_id,
            aweme_id=item.aweme_id,
            url=item.url,
            title=item.title,
            author=item.author,
            type=item.type,
            status=item.status,
            downloaded_bytes=item.downloaded_bytes,
            total_bytes=item.total_bytes,
            progress=(
                100.0
                if item.status == "completed"
                else (
                    (item.downloaded_bytes / max(item.total_bytes, 1)) * 100
                    if item.total_bytes > 0
                    else 0.0
                )
            ),
            cover_url=item.cover_url,
            fail_reason=item.fail_reason,
            local_path=item.local_path,
        )
        for item in items
    ]


@router.post("/start")
async def start_download(req: StartDownloadRequest):
    """启动下载任务。"""
    if (
        ctx.task_repo is None
        or ctx.task_item_repo is None
        or ctx.scheduler is None
        or ctx.config_repo is None
    ):
        raise HTTPException(status_code=503, detail="Service not ready")

    download_dir = req.download_dir or ctx.config_repo.get("download_dir") or ""

    # 创建任务
    task = Task(
        id=None,
        source_type=req.source_type,
        source_url=req.source_url,
        status=TaskStatus.PENDING.value,
        download_dir=download_dir,
    )
    task_id = ctx.task_repo.create(task)

    # 如果有传入 items，直接创建 task_items 并入队
    if req.items:
        items = []
        # 获取有效 Cookie（供二次解析真实媒体地址）
        cookie = ""
        if ctx.cookie_repo is not None:
            valid_cookie = ctx.cookie_repo.get_valid()
            if valid_cookie is not None:
                cookie = valid_cookie.content
                ctx.cookie_repo.update_last_used(valid_cookie.id, now_iso())

        for item_data in req.items:
            item_type = item_data.get("type", "video")
            aweme_id = item_data.get("aweme_id")
            media_url = item_data.get("no_watermark_url") or ""
            image_urls = item_data.get("image_urls") or []
            item_video_urls = item_data.get("item_video_urls") or []
            item_types = item_data.get("item_types") or []

            # 前端未提供真实媒体地址时，用 aweme_id 二次解析 detail 接口获取
            if not (media_url or image_urls) and aweme_id and ctx.video_parser is not None:
                try:
                    video_info = await ctx.video_parser.parse_video(aweme_id, cookie)
                    if item_type == "image_set" and video_info.image_urls:
                        image_urls = video_info.image_urls
                        item_video_urls = video_info.item_video_urls
                        item_types = video_info.item_types
                    elif video_info.no_watermark_url:
                        media_url = video_info.no_watermark_url
                except Exception:
                    # 解析失败时回退到原始 URL，交由下载器/用户界面反馈
                    pass

            # 图集：优先使用逐项视频直链（有视频的项下载视频，其余退枝到图片）
            if item_type == "image_set":
                # 仅在有视频直链的项上使用视频 URL，其余保留图片 URL
                if item_video_urls and len(item_video_urls) == len(image_urls):
                    download_urls = [
                        v if v else i
                        for v, i in zip(item_video_urls, image_urls, strict=True)
                    ]
                else:
                    download_urls = image_urls
                download_url = "\n".join(download_urls) if download_urls else ""
            elif media_url:
                download_url = media_url
            else:
                download_url = item_data.get("url", "")

            task_item = TaskItem(
                id=None,
                task_id=task_id,
                aweme_id=aweme_id,
                url=download_url,
                title=item_data.get("title"),
                author=item_data.get("author"),
                type=item_type,
                cover_url=item_data.get("cover_url"),
                image_count=(
                    len(image_urls)
                    if item_type == "image_set" and image_urls
                    else item_data.get("image_count")
                ),
                item_types=json.dumps(item_types, ensure_ascii=False) if item_type == "image_set" and item_types else "",
                status=TaskItemStatus.PENDING.value,
            )
            item_id = ctx.task_item_repo.create(task_item)
            task_item.id = item_id
            items.append(task_item)

        # 更新任务总数
        ctx.task_repo.update_progress(task_id, 0, len(items))

        # 入队调度
        ctx.scheduler.add_task_items(items)

    return {"task_id": task_id, "message": "下载任务已创建"}


@router.post("/pause/{task_item_id}")
async def pause_download(task_item_id: int):
    """暂停指定下载项。"""
    if ctx.scheduler is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    await ctx.scheduler.pause(task_item_id)
    return {"message": f"task_item {task_item_id} 已暂停"}


@router.post("/resume/{task_item_id}")
async def resume_download(task_item_id: int):
    """恢复指定下载项。"""
    if ctx.scheduler is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    await ctx.scheduler.resume(task_item_id)
    return {"message": f"task_item {task_item_id} 已恢复"}


@router.post("/retry/{task_item_id}")
async def retry_download(task_item_id: int):
    """重新执行下载项：重置为待下载状态并重新入队。"""
    if ctx.task_item_repo is None or ctx.scheduler is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    item = ctx.task_item_repo.get(task_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="任务项不存在")
    ctx.task_item_repo.reset_for_retry(task_item_id)
    # 状态已重置为 pending，不会被已完成去重跳过
    ctx.scheduler.add_task_items([item])
    return {"message": f"任务项 {task_item_id} 已重新入队"}


@router.post("/retry-all")
async def retry_all_failed():
    """将所有失败状态的任务项重新入队。

    遍历所有 failed 状态的任务项，逐个重置为 pending 后重新加入下载队列。
    """
    if ctx.task_item_repo is None or ctx.scheduler is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    failed_items = ctx.task_item_repo.get_by_status("failed")
    if not failed_items:
        return {"message": "没有失败任务", "retried_count": 0}

    for item in failed_items:
        if item.id is not None:
            ctx.task_item_repo.reset_for_retry(item.id)

    # 重新入队（reset_for_retry 已将状态置为 pending，不会被去重跳过）
    ctx.scheduler.add_task_items(failed_items)

    return {
        "message": f"已重新入队 {len(failed_items)} 个失败任务",
        "retried_count": len(failed_items),
    }


@router.post("/pause-all")
async def pause_all():
    """暂停所有下载。"""
    if ctx.scheduler is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    await ctx.scheduler.pause_all()
    return {"message": "所有下载已暂停"}


@router.post("/resume-all")
async def resume_all():
    """恢复所有暂停的下载。"""
    if ctx.scheduler is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    await ctx.scheduler.resume_all()
    return {"message": "所有暂停任务已恢复"}


@router.delete("/tasks/items/{item_id}")
async def delete_task_item(item_id: int):
    """删除单个下载任务项。

    若该项所属 Task 下已无剩余 TaskItem，则一并清理该 Task。
    """
    if ctx.task_item_repo is None or ctx.task_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    item = ctx.task_item_repo.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"任务项 {item_id} 不存在")

    task_id = item.task_id

    # 删除该 TaskItem
    ctx.task_item_repo.delete(item_id)

    # 检查所属 Task 下是否还有剩余项，若无则清理 Task
    remaining = ctx.task_item_repo.get_by_task(task_id)
    if not remaining:
        ctx.task_repo.delete(task_id)

    return {"message": f"任务项 {item_id} 已删除"}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    """删除任务及其所有项。"""
    if ctx.task_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    ctx.task_repo.delete(task_id)
    return {"message": f"任务 {task_id} 已删除"}


@router.post("/clear-completed")
async def clear_completed():
    """清除所有已完成的任务项及空父任务。"""
    if ctx.task_repo is None or ctx.task_item_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    completed_items = ctx.task_item_repo.get_by_status(TaskStatus.COMPLETED.value)
    affected_tasks: set[int] = set()

    for item in completed_items:
        if item.id is not None:
            ctx.task_item_repo.delete(item.id)
            affected_tasks.add(item.task_id)

    # 清理没有剩余 task_items 的空父任务
    for task_id in affected_tasks:
        remaining = ctx.task_item_repo.get_by_task(task_id)
        if not remaining:
            ctx.task_repo.delete(task_id)

    return {"message": f"已清除 {len(completed_items)} 个已完成任务项"}


@router.post("/verify")
async def verify_completed_files():
    """校验所有已完成任务的本地文件是否存在。

    遍历所有 completed 状态的任务项，检查 local_path 对应的文件是否真实存在于磁盘。
    若文件不存在，自动将状态重置为 failed（带原因说明）。
    返回校验结果统计。

    修复说明：
    - 对 local_path 进行 os.path.normpath + os.path.abspath 规范化，解决 Windows 路径问题
    - 双重校验：os.path.isfile + os.path.exists + os.path.getsize > 0
    - 增强日志记录，便于调试
    """
    if ctx.task_item_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    completed_items = ctx.task_item_repo.get_by_status(TaskStatus.COMPLETED.value)
    missing_items: list[dict] = []
    verified_count = 0

    for item in completed_items:
        if item.id is None:
            continue
        verified_count += 1
        if item.local_path:
            # 路径规范化：统一正斜杠、转为绝对路径
            normalized_path = os.path.normpath(os.path.abspath(item.local_path))
            if (
                os.path.isfile(normalized_path)
                and os.path.exists(normalized_path)
                and os.path.getsize(normalized_path) > 0
            ):
                continue
            logger.warning(
                "文件校验失败: item_id=%s, local_path=%r, normalized=%r, "
                "isfile=%s, exists=%s, size=%s",
                item.id,
                item.local_path,
                normalized_path,
                os.path.isfile(normalized_path),
                os.path.exists(normalized_path),
                os.path.getsize(normalized_path) if os.path.exists(normalized_path) else "N/A",
            )
        # 文件不存在：重置为 failed
        ctx.task_item_repo.update_status(
            item.id,
            TaskItemStatus.FAILED.value,
            fail_reason="文件不存在（可能已被外部删除）",
        )
        missing_items.append(
            {
                "id": item.id,
                "aweme_id": item.aweme_id,
                "title": item.title,
                "local_path": item.local_path,
            }
        )

    return {
        "verified_count": verified_count,
        "missing_count": len(missing_items),
        "missing_items": missing_items,
    }