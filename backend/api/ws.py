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


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket 主端点。

    前端连接后，服务端会持续推送进度更新和状态变化。
    前端可发送控制消息：
    - {"type": "ping"} → 服务端回复 pong
    """
    await manager.connect(ws)
    logger.info("WebSocket 客户端已连接，当前连接数: %d", manager.active_count)

    try:
        # 发送连接成功消息
        await ws.send_json({"type": "connected", "message": "WebSocket 已连接"})

        # 启动进度推送任务（如果调度器存在）
        stop_event = asyncio.Event()
        progress_task = asyncio.create_task(_push_progress_updates(ws, stop_event))

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
        if "progress_task" in locals():
            progress_task.cancel()
        logger.info("WebSocket 连接已清理，当前连接数: %d", manager.active_count)


async def _push_progress_updates(ws: WebSocket, stop_event: asyncio.Event) -> None:
    """定期推送进度更新。

    每 1 秒推送一次 downloading/completed/failed 任务项的进度。
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
                    await ws.send_json(
                        {
                            "type": "progress",
                            "updates": all_updates,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
        except Exception:
            pass
        await asyncio.sleep(1)
