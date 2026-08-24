/** WebSocket 连接管理 hook
 *
 * 使用 tauri-plugin-websocket（官方 Rust 侧 WebSocket 插件）建立连接，
 * 绕过 Tauri 打包版 WebView2 对 ws:// 的混合内容限制。
 * 非 Tauri 环境（浏览器开发模式）自动回退到原生 WebSocket。
 */

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
  const wsRef = useRef<any>(null);
  const [connected, setConnected] = useState(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const removeListenerRef = useRef<(() => void) | null>(null);
  const isConnectingRef = useRef(false);

  const connect = useCallback(async () => {
    // 防止并发重连
    if (isConnectingRef.current) return;
    isConnectingRef.current = true;

    try {
      // 清理旧连接
      if (wsRef.current) {
        try { removeListenerRef.current?.(); } catch { /* ignore */ }
        try { await wsRef.current.disconnect?.(); } catch { /* ignore */ }
        try { wsRef.current.close?.(); } catch { /* ignore */ }
        wsRef.current = null;
      }

      // 尝试使用 Tauri 插件（Rust 侧 WebSocket）
      let useTauriPlugin = false;
      try {
        const mod = await import("@tauri-apps/plugin-websocket");
        const TauriWebSocket = mod.default;
        const ws = await TauriWebSocket.connect(WS_URL);
        wsRef.current = ws;
        useTauriPlugin = true;
        setConnected(true);

        const remove = ws.addListener((msg: any) => {
          if (msg.type === "Text") {
            try {
              const parsed = JSON.parse(msg.data) as WsMessage;
              onMessage?.(parsed);
            } catch { /* JSON parse error, ignore */ }
          } else if (msg.type === "Close") {
            // 服务端关闭连接 → 重连
            setConnected(false);
            reconnectTimer.current = setTimeout(connect, 3000);
          }
        });
        removeListenerRef.current = remove;
      } catch {
        // Tauri 插件不可用（非 Tauri 环境或插件未初始化）→ 回退原生 WebSocket
        if (!useTauriPlugin) {
          const ws = new window.WebSocket(WS_URL);
          wsRef.current = ws;

          ws.onopen = () => {
            setConnected(true);
          };

          ws.onmessage = (event: MessageEvent) => {
            try {
              const parsed = JSON.parse(event.data) as WsMessage;
              onMessage?.(parsed);
            } catch { /* JSON parse error, ignore */ }
          };

          ws.onclose = () => {
            setConnected(false);
            reconnectTimer.current = setTimeout(connect, 3000);
          };

          ws.onerror = () => {
            ws.close();
          };
        }
      }
    } catch (e) {
      console.warn("[WS] 连接失败，3秒后重试", e);
      setConnected(false);
      reconnectTimer.current = setTimeout(connect, 3000);
    } finally {
      isConnectingRef.current = false;
    }
  }, [onMessage]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current ?? undefined);
      if (wsRef.current) {
        try { removeListenerRef.current?.(); } catch { /* ignore */ }
        try { wsRef.current.disconnect?.(); } catch { /* ignore */ }
        try { wsRef.current.close?.(); } catch { /* ignore */ }
      }
      isConnectingRef.current = false;
    };
  }, [connect]);

  return { connected };
}