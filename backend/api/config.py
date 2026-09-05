"""配置 REST API。

提供下载目录、并发数、分块大小、元数据格式等配置读写能力。
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import DEFAULT_CONFIGS
from backend.state import ctx

router = APIRouter()

# 审计 M5：custom_sound_url 准入扩展名（new Audio / play_wav_sound 使用）
_SOUND_EXTENSIONS: tuple[str, ...] = (".mp3", ".wav", ".ogg", ".m4a", ".aac")


def _validate_sound_url(value: str) -> None:
    """custom_sound_url 准入：http(s)/file URL 或本地绝对路径，且为音频扩展名。

    参数:
        value: 待校验的 custom_sound_url（空串表示清除，直接放行）。

    异常:
        HTTPException(400): 扩展名或格式不合法。
    """
    if not value:
        return
    lower = value.lower()
    if not lower.endswith(_SOUND_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail="custom_sound_url 仅支持音频文件（mp3/wav/ogg/m4a/aac）",
        )
    parts = urlsplit(value)
    if parts.scheme in ("http", "https", "file") and parts.hostname:
        return
    if os.path.isabs(value):  # Windows 盘符路径 / UNC 路径
        return
    raise HTTPException(
        status_code=400,
        detail="custom_sound_url 格式不支持，需为 http(s)/file URL 或本地绝对路径",
    )


# === 请求/响应模型 ===


class ConfigResponse(BaseModel):
    """配置响应。"""

    download_dir: str
    concurrency: int
    chunk_size: int
    metadata_format: str
    onboarding_done: bool
    notification_enabled: bool
    sound_enabled: bool
    sound_choice: str
    sound_volume: float
    custom_sound_url: str


class UpdateConfigRequest(BaseModel):
    """更新配置请求。"""

    download_dir: str | None = None
    concurrency: int | None = None
    chunk_size: int | None = None
    metadata_format: str | None = None
    onboarding_done: bool | None = None
    notification_enabled: bool | None = None
    sound_enabled: bool | None = None
    sound_choice: str | None = None
    sound_volume: float | None = None
    custom_sound_url: str | None = None


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
        onboarding_done=config.get("onboarding_done", "false") == "true",
        notification_enabled=config.get("notification_enabled", "true") == "true",
        sound_enabled=config.get("sound_enabled", "true") == "true",
        sound_choice=config.get("sound_choice", "default"),
        sound_volume=float(config.get("sound_volume", "0.5")),
        custom_sound_url=config.get("custom_sound_url", ""),
    )


@router.post("")
async def update_config(req: UpdateConfigRequest):
    """更新配置。"""
    if ctx.config_repo is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    if req.download_dir is not None:
        raw = req.download_dir.strip()
        if not raw:
            raise HTTPException(status_code=400, detail="下载目录不能为空")
        # 审计 N2：规范化存储（展开用户目录 + 绝对路径），
        # 与入队接口的 _validate_download_dir 严格一致校验配套
        abs_dir = os.path.abspath(os.path.expanduser(raw))
        ctx.config_repo.set("download_dir", abs_dir)
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
    if req.notification_enabled is not None:
        ctx.config_repo.set("notification_enabled", "true" if req.notification_enabled else "false")
    if req.sound_enabled is not None:
        ctx.config_repo.set("sound_enabled", "true" if req.sound_enabled else "false")
    if req.sound_choice is not None:
        ctx.config_repo.set("sound_choice", req.sound_choice)
    if req.sound_volume is not None:
        ctx.config_repo.set("sound_volume", str(req.sound_volume))
    if req.custom_sound_url is not None:
        # 审计 M5：拦截非音频扩展名/内网探测型 URL（new Audio 会发起请求）
        _validate_sound_url(req.custom_sound_url)
        ctx.config_repo.set("custom_sound_url", req.custom_sound_url)

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
