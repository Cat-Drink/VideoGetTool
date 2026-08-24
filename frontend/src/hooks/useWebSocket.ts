/** WebSocket 连接管理 hook */

import { useEffect, useRef, useCallback, useState } from "react";

const WS_URL = "ws://127.0.0.1:18989/api/ws";

export interface ProgressUpdate {
  task_item_id: number;
  downloaded_bytes: number;
  total_bytes: number;
  progress: number;
  status: string;
  aweme_id: string | null;
}

export interface WsMessage {
  type: string;
  updates?: ProgressUpdate[];
  task_id?: number;
  task_item_id?: number;
  fail_reason?: string;
  completed_count?: number;
  failed_count?: number;
  total_count?: number;
  message?: string;
  timestamp?: string;
}

export function useWebSocket(onMessage?: (msg: WsMessage) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        console.log("[WS] 已连接");
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WsMessage;
          onMessage?.(msg);
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        setConnected(false);
        console.log("[WS] 连接断开，3秒后重连");
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      // connection error, retry
      reconnectTimer.current = setTimeout(connect, 3000);
    }
  }, [onMessage]);

  const send = useCallback((data: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current ?? undefined);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, send };
}