"""WebSocket 进度通道。

把下载进度、解析进度、状态变化推送给前端。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.state import ctx

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket 连接管理器。

    管理多个前端连接，支持广播消息。
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """向所有连接广播消息。"""
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()

# 共享进度轮询任务：每 1 秒查一次数据库，广播给所有 WebSocket 连接
# 替代原先每个连接各自轮询（N 个连接 = N 次/秒查询）的模式
_push_stop_event: asyncio.Event | None = None


async def _start_shared_push() -> None:
    """启动共享进度轮询任务。"""
    global _push_stop_event
    _push_stop_event = asyncio.Event()
    asyncio.create_task(_push_progress_updates(_push_stop_event))


async def _stop_shared_push() -> None:
    """停止共享进度轮询任务。"""
    if _push_stop_event is not None:
        _push_stop_event.set()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket 主端点。

    前端连接后，进度更新由调度器回调（_on_progress）和共享轮询任务
    共同推送，每个连接不再独立轮询数据库。
    """
    await manager.connect(ws)
    logger.info("WebSocket 客户端已连接，当前连接数: %d", manager.active_count)

    try:
        # 发送连接成功消息
        await ws.send_json({"type": "connected", "message": "WebSocket 已连接"})

        # 监听前端消息
        while True:
            try:
                data = await ws.receive_text()
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
                elif msg.get("type") == "subscribe":
                    await ws.send_json(
                        {
                            "type": "subscribed",
                            "channel": msg.get("channel", "all"),
                        }
                    )
            except (json.JSONDecodeError, KeyError):
                await ws.send_json({"type": "error", "message": "无效的消息格式"})

    except WebSocketDisconnect:
        logger.info("WebSocket 客户端已断开")
    except Exception as e:
        logger.error("WebSocket 错误: %s", e)
    finally:
        manager.disconnect(ws)
        logger.info("WebSocket 连接已清理，当前连接数: %d", manager.active_count)


async def _push_progress_updates(stop_event: asyncio.Event) -> None:
    """定期推送进度更新（共享任务，广播给所有连接）。

    每 1 秒推送一次 downloading/completed/failed 任务项的进度。
    使用 manager.broadcast 替代原先每个连接独立轮询，避免 N 个连接
    产生 N 次/秒的数据库查询。
    """
    while not stop_event.is_set():
        try:
            if ctx.task_item_repo is not None:
                all_updates: list[dict] = []

                for status in ("downloading", "processing", "completed", "failed"):
                    items = ctx.task_item_repo.get_by_status(status)
                    for item in items:
                        if item.id is None:
                            continue

                        progress: float = 0.0
                        if status == "completed":
                            progress = 100.0
                        elif item.total_bytes > 0:
                            progress = (item.downloaded_bytes / item.total_bytes) * 100.0

                        all_updates.append(
                            {
                                "task_item_id": item.id,
                                "downloaded_bytes": item.downloaded_bytes,
                                "total_bytes": item.total_bytes,
                                "progress": round(progress, 1),
                                "status": item.status,
                                "aweme_id": item.aweme_id,
                            }
                        )

                if all_updates:
                    await manager.broadcast(
                        {
                            "type": "progress",
                            "updates": all_updates,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
        except Exception:
            pass
        await asyncio.sleep(1)
