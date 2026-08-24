/** WebSocket 连接管理 hook
 *
 * 使用官方 tauri-plugin-websocket（Rust 侧 WebSocket，绕过 WebView 混合内容限制）。
 * 非 Tauri 环境（浏览器开发模式）自动回退到原生 WebSocket。
 *
 * 关键设计：
 * - 在 Tauri 环境中，插件连接失败时保持插件模式重试，绝不降级到原生 WebSocket
 *   （原生 WebSocket 在打包版中因混合内容限制永远无法连接）
 * - 使用 onMessageRef 避免 connect 依赖 onMessage，防止 connect 引用变化导致频繁重连
 */

import { useEffect, useRef, useCallback, useState } from "react";
import TauriWebSocket from "@tauri-apps/plugin-websocket";

const WS_URL = "ws://127.0.0.1:18989/api/ws";

/** Tauri 2 IPC 一定存在于打包 WebView 中，比 isTauri 全局标记更可靠。 */
function isTauriRuntime(): boolean {
  return typeof window !== "undefined" &&
    typeof (window as any).__TAURI_INTERNALS__?.invoke === "function";
}

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

/** 关闭当前 WebSocket 连接（兼容两种模式） */
async function closeConnection(ws: any, removeListener: (() => void) | null) {
  try { removeListener?.(); } catch { /* ignore */ }
  if (ws) {
    try { await ws.disconnect?.(); } catch { /* ignore */ }
    try { ws.close?.(); } catch { /* ignore */ }
  }
}

export function useWebSocket(onMessage?: (msg: WsMessage) => void) {
  const wsRef = useRef<any>(null);
  const [connected, setConnected] = useState(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const removeListenerRef = useRef<(() => void) | null>(null);
  const isConnectingRef = useRef(false);
  // 用 ref 保存最新的 onMessage，避免 connect 回调闭包陈旧
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const connect = useCallback(async () => {
    if (isConnectingRef.current) return;
    isConnectingRef.current = true;

    try {
      // 清理旧连接
      if (wsRef.current) {
        await closeConnection(wsRef.current, removeListenerRef.current);
        wsRef.current = null;
        removeListenerRef.current = null;
      }

      // 只在 Tauri 运行时使用 Rust 侧插件；浏览器开发模式使用原生 WebSocket
      const runningInTauri = isTauriRuntime();
      console.log(`[WS] 运行环境: ${runningInTauri ? "Tauri" : "浏览器"}`);

      if (runningInTauri) {
        // ═══ Tauri 插件模式：Rust 侧 WebSocket（绕过 WebView 限制）═══
        try {
          console.log("[WS] 正在连接（Tauri 插件模式）...");
          const ws = await TauriWebSocket.connect(WS_URL);
          wsRef.current = ws;
          setConnected(true);
          console.log("[WS] 已连接（Tauri 插件模式）");

          // 注册消息监听
          const remove = ws.addListener((msg: any) => {
            if (msg.type === "Text") {
              try {
                const parsed = JSON.parse(msg.data) as WsMessage;
                onMessageRef.current?.(parsed);
              } catch { /* JSON parse error */ }
            } else if (msg.type === "Close") {
              console.log("[WS] 连接关闭（Close 帧），3秒后重连");
              setConnected(false);
              reconnectTimer.current = setTimeout(connect, 3000);
            }
          });
          removeListenerRef.current = remove;
          return;
        } catch (e) {
          // 插件连接失败 → 保持插件模式重试，绝不降级到原生 WebSocket
          console.warn("[WS] Tauri 插件连接失败，3秒后重试:", e);
          setConnected(false);
          reconnectTimer.current = setTimeout(connect, 3000);
          return;
        }
      }

      // ═══ 非 Tauri 环境：浏览器原生 WebSocket（开发模式降级）═══
      try {
        console.log("[WS] 正在连接（原生模式）...");
        const ws = new window.WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          setConnected(true);
          console.log("[WS] 已连接（原生模式）");
        };

        ws.onmessage = (event: MessageEvent) => {
          try {
            const parsed = JSON.parse(event.data) as WsMessage;
            onMessageRef.current?.(parsed);
          } catch { /* JSON parse error */ }
        };

        ws.onclose = () => {
          console.log("[WS] 原生连接断开，3秒后重连");
          setConnected(false);
          reconnectTimer.current = setTimeout(connect, 3000);
        };

        ws.onerror = () => {
          ws.close();
        };
      } catch (e) {
        console.warn("[WS] 原生连接失败，3秒后重试:", e);
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 3000);
      }
    } finally {
      isConnectingRef.current = false;
    }
  }, []); // 无依赖——connect 引用稳定，不会无故重连

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current ?? undefined);
      if (wsRef.current) {
        closeConnection(wsRef.current, removeListenerRef.current);
      }
      isConnectingRef.current = false;
    };
  }, [connect]);

  return { connected };
}