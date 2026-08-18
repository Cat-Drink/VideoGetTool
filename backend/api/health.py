"""健康检查接口。

提供服务健康检查和就绪状态，供 Tauri 与前端确认 sidecar 是否可用。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.state import ctx

router = APIRouter()


@router.get("/health")
async def health_check():
    """基础健康检查：服务是否运行。"""
    return {"status": "ok", "service": "python-sidecar", "version": "0.3.0"}


@router.get("/ready")
async def readiness_check():
    """就绪检查：数据库和调度器是否可用。

    未就绪时返回 HTTP 503，便于负载均衡器/编排系统识别。
    """
    db_ok = ctx.conn is not None
    scheduler_ok = ctx.scheduler is not None
    if db_ok and scheduler_ok:
        return {"status": "ready", "database": "connected", "scheduler": "running"}
    raise HTTPException(
        status_code=503,
        detail={
            "status": "not_ready",
            "database": "connected" if db_ok else "disconnected",
            "scheduler": "running" if scheduler_ok else "stopped",
        },
    )
