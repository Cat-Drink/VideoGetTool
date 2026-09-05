"""下载任务 REST API。

暴露任务列表、启动下载、暂停/恢复/重试、清除已完成等接口。
"""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import Task, TaskItem, TaskItemStatus, TaskStatus, now_iso
from backend.state import ctx

router = APIRouter()
logger = logging.getLogger(__name__)


# === 内部辅助 ===


def _resolve_dir(path: str) -> str:
    """规范化目录：展开用户目录、取绝对路径、统一大小写（Windows）。"""
    return os.path.normcase(os.path.abspath(os.path.expanduser(path.strip())))


def _validate_download_dir(raw: str | None, configured: str) -> str:
    """下载目录准入：仅接受『与配置目录一致』的路径（审计 P0-3/N2）。

    产品语义：下载目录只能经“设置页 → config API”变更；入队接口收到的
    download_dir 必须与配置一致，否则拒绝。这同时封堵 config API 之外
    的任意路径写（DNS rebinding 的第二个写入点）。

    参数:
        raw: 请求传入的 download_dir（可空）
        configured: 配置中的 download_dir

    返回:
        校验通过的下载目录（非空字符串）

    异常:
        HTTPException(400): 目录为空或与配置不一致
    """
    candidate = (raw or configured or "").strip()
    if not candidate:
        # 配置缺失时回退内置默认目录（生产环境 init_db 总会写入默认值）
        from app.config import DEFAULT_CONFIGS

        candidate = DEFAULT_CONFIGS.get("download_dir", "").strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="下载目录为空")
    if configured.strip():
        if _resolve_dir(candidate) != _resolve_dir(configured):
            raise HTTPException(
                status_code=400,
                detail="download_dir 与配置目录不一致，请在设置中修改下载目录",
            )
    return candidate


_ALLOWED_DOWNLOAD_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def _validate_download_url(url: str) -> str:
    """下载直链校验：仅 http/https、必须有 host（审计 P0-3）。

    参数:
        url: 待校验的直链 URL（可空字符串）

    返回:
        规范化后的 URL（空串原样返回）

    异常:
        HTTPException(400): 协议非 http/https 或缺少 host
    """
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_DOWNLOAD_SCHEMES or not parts.hostname:
        raise HTTPException(status_code=400, detail=f"非法下载地址: {url[:80]}")
    return url


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


# === 内部辅助 ===


async def enqueue_download_items(
    source_type: str,
    source_url: str | None,
    items: list[dict],
    download_dir: str | None = None,
) -> int:
    """创建下载任务并入队调度（供 start_download 与订阅模式共用）。

    流程：
        1. 创建 Task（source_type / source_url / download_dir）
        2. 逐项解析真实媒体地址（前端未提供时用 aweme_id 二次解析 detail 接口）
        3. 创建 TaskItems 并更新任务进度
        4. 交给 Scheduler 入队

    Args:
        source_type: 任务来源类型（single/batch/user_home/subscription 等）
        source_url: 来源链接（可空）
        items: 待下载 item dict 列表
        download_dir: 下载目录，None 时使用配置默认值

    Returns:
        新建任务 id

    Raises:
        HTTPException(503): 基础设施未就绪
    """
    if (
        ctx.task_repo is None
        or ctx.task_item_repo is None
        or ctx.scheduler is None
        or ctx.config_repo is None
    ):
        raise HTTPException(status_code=503, detail="Service not ready")

    # 审计 P0-3：download_dir 必须与配置目录一致（封堵任意路径写）
    download_dir = _validate_download_dir(
        download_dir, ctx.config_repo.get("download_dir") or ""
    )

    # 创建任务
    task = Task(
        id=None,
        source_type=source_type,
        source_url=source_url,
        status=TaskStatus.PENDING.value,
        download_dir=download_dir,
    )
    task_id = ctx.task_repo.create(task)

    # 有 items 时创建 task_items 并入队
    if items:
        task_items = []
        # 获取有效 Cookie（供二次解析真实媒体地址）
        cookie = ""
        if ctx.cookie_repo is not None:
            valid_cookie = ctx.cookie_repo.get_valid()
            if valid_cookie is not None:
                cookie = valid_cookie.content
                ctx.cookie_repo.update_last_used(valid_cookie.id, now_iso())

        for item_data in items:
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
                        v if v else i for v, i in zip(item_video_urls, image_urls, strict=True)
                    ]
                else:
                    download_urls = image_urls
                download_url = "\n".join(download_urls) if download_urls else ""
            elif media_url:
                download_url = media_url
            else:
                download_url = item_data.get("url", "")

            # 审计 P0-3：所有落库直链一律校验（仅 http/https）
            if download_url:
                download_url = "\n".join(
                    _validate_download_url(u) for u in download_url.split("\n") if u
                )

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
                item_types=(
                    json.dumps(item_types, ensure_ascii=False)
                    if item_type == "image_set" and item_types
                    else ""
                ),
                status=TaskItemStatus.PENDING.value,
                # v0.4.0：B 站 DASH 字段透传
                bvid=item_data.get("bvid"),
                cid=item_data.get("cid"),
                page=item_data.get("page") or 0,
                audio_url=_validate_download_url(item_data.get("audio_url")),
                dash_merged="",
            )
            item_id = ctx.task_item_repo.create(task_item)
            task_item.id = item_id
            task_items.append(task_item)

        # 更新任务总数
        ctx.task_repo.update_progress(task_id, 0, len(task_items))

        # 入队调度
        ctx.scheduler.add_task_items(task_items)

    return task_id


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


def _remove_item_outputs(item: TaskItem, task_repo) -> None:
    """删除任务项对应的本地产物（审计 S3）。

    仅当任务项已生成本地文件（local_path 非空）时尝试清理；目录包含性
    校验基座取任务自身的 download_dir（同一任务内安全），越界/失败仅记
    日志不抛错，避免单个产物删除失败阻断整个删除请求。

    参数:
        item: 待删除的任务项。
        task_repo: Task 仓库（用于取任务 download_dir）。
    """
    if not item.local_path:
        return
    try:
        from downloader.cleanup import safe_remove_output

        base_dir = ""
        task = task_repo.get(item.task_id) if task_repo else None
        base_dir = (task.download_dir if task else "") or ""
        if not base_dir:
            logger.warning("任务项 %s 无 download_dir，跳过产物清理", item.id)
            return
        safe_remove_output(item.local_path, base_dir)
    except Exception:  # 清理失败绝不阻断数据库删除
        logger.exception("任务项 %s 产物清理异常（忽略）", item.id)


@router.post("/start")
async def start_download(req: StartDownloadRequest):
    """启动下载任务。"""
    task_id = await enqueue_download_items(
        source_type=req.source_type,
        source_url=req.source_url,
        items=req.items or [],
        download_dir=req.download_dir,
    )
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
    审计 S3：删除数据库行的同时清理该项的本地产物（成品文件/.part），
    目录包含性校验见 ``downloader.cleanup.safe_remove_output``；
    产物路径越界或删除失败仅记录日志，不影响数据库删除。
    """
    if ctx.task_item_repo is None or ctx.task_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    item = ctx.task_item_repo.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"任务项 {item_id} 不存在")

    task_id = item.task_id

    # 审计 S3：先清理本地产物（含 .part），再删数据库行
    _remove_item_outputs(item, ctx.task_repo)

    # 删除该 TaskItem
    ctx.task_item_repo.delete(item_id)

    # 检查所属 Task 下是否还有剩余项，若无则清理 Task
    remaining = ctx.task_item_repo.get_by_task(task_id)
    if not remaining:
        ctx.task_repo.delete(task_id)

    return {"message": f"任务项 {item_id} 已删除"}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    """删除任务及其所有项。

    审计 S3：删除数据库行的同时清理任务全部项的本地产物（成品/.part），
    目录包含性校验见 ``downloader.cleanup.safe_remove_output``。
    """
    if ctx.task_repo is None or ctx.task_item_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    task = ctx.task_repo.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    # 审计 S3：先清理全部子项的本地产物，再删数据库行
    for item in ctx.task_item_repo.get_by_task(task_id):
        _remove_item_outputs(item, ctx.task_repo)
    # TaskRepository.delete 依赖外键 ON DELETE CASCADE 级联删除 task_items/metadata
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
