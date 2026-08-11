"""配置 REST API。

提供下载目录、并发数、分块大小、元数据格式等配置读写能力。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.state import ctx
from app.config import DEFAULT_CONFIGS

router = APIRouter()


# === 请求/响应模型 ===


class ConfigResponse(BaseModel):
    """配置响应。"""

    download_dir: str
    concurrency: int
    chunk_size: int
    metadata_format: str
    webp_auto_convert: bool
    onboarding_done: bool


class UpdateConfigRequest(BaseModel):
    """更新配置请求。"""

    download_dir: str | None = None
    concurrency: int | None = None
    chunk_size: int | None = None
    metadata_format: str | None = None
    webp_auto_convert: bool | None = None
    onboarding_done: bool | None = None


# === API 端点 ===


@router.get("", response_model=ConfigResponse)
async def get_config():
    """获取所有配置。"""
    if ctx.config_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    config = ctx.config_repo.get_all()
    return ConfigResponse(
        download_dir=config.get("download_dir", ""),
        concurrency=int(config.get("concurrency", "3")),
        chunk_size=int(config.get("chunk_size", "1048576")),
        metadata_format=config.get("metadata_format", "json"),
        webp_auto_convert=config.get("webp_auto_convert", "true") == "true",
        onboarding_done=config.get("onboarding_done", "false") == "true",
    )


@router.post("")
async def update_config(req: UpdateConfigRequest):
    """更新配置。"""
    if ctx.config_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    if req.download_dir is not None:
        ctx.config_repo.set("download_dir", req.download_dir)
    if req.concurrency is not None:
        ctx.config_repo.set("concurrency", str(req.concurrency))
        # 动态调整调度器并发数
        if ctx.scheduler is not None:
            ctx.scheduler.set_max_concurrent(req.concurrency)
    if req.chunk_size is not None:
        ctx.config_repo.set("chunk_size", str(req.chunk_size))
    if req.metadata_format is not None:
        ctx.config_repo.set("metadata_format", req.metadata_format)
    if req.onboarding_done is not None:
        ctx.config_repo.set("onboarding_done", "true" if req.onboarding_done else "false")
    if req.webp_auto_convert is not None:
        ctx.config_repo.set("webp_auto_convert", "true" if req.webp_auto_convert else "false")

    return {"message": "配置已更新"}


@router.post("/reset")
async def reset_config():
    """重置所有配置为默认值。"""
    if ctx.config_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    for key, value in DEFAULT_CONFIGS.items():
        ctx.config_repo.set(key, value)
    # 恢复默认并发数
    if ctx.scheduler is not None:
        ctx.scheduler.set_max_concurrent(int(DEFAULT_CONFIGS["concurrency"]))
    return {"message": "配置已重置"}


@router.get("/{key}")
async def get_config_item(key: str):
    """获取单个配置项。"""
    if ctx.config_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    value = ctx.config_repo.get(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"配置项 {key} 不存在")
    return {"key": key, "value": value}
