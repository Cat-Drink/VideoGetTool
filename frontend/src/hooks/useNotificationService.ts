/** 全局通知服务 Hook
 *
 * 在 App 层挂载，独立于 DownloadPage 运行。
 * 通过 WebSocket 监听 Task 级事件（task_completed / task_failed），
 * 触发系统通知、Toast 提示和音效。
 * 确保即使焦点不在下载页面也能收到通知。
 */

import { useCallback, useRef } from "react";
import { useWebSocket, type WsMessage } from "./useWebSocket";
import { useToastStore } from "../store/toastStore";
import { playNotificationSound } from "../lib/sound";
import { sendSystemNotification } from "../lib/notify";
import * as api from "../lib/api";

interface NotifySettings {
  notificationEnabled: boolean;
  soundEnabled: boolean;
  soundChoice: "default" | "soft" | "cheerful" | "custom" | "custom_wav";
  soundVolume: number;
  customSoundUrl: string;
}

/** 从配置加载通知设置（缓存结果，避免频繁读取） */
let cachedSettings: NotifySettings | null = null;

async function getNotifySettings(): Promise<NotifySettings> {
  if (cachedSettings) return cachedSettings;
  try {
    const cfg = await api.fetchConfig();
    cachedSettings = {
      notificationEnabled: cfg.notification_enabled,
      soundEnabled: cfg.sound_enabled,
      soundChoice: cfg.sound_choice as NotifySettings["soundChoice"],
      soundVolume: cfg.sound_volume,
      customSoundUrl: cfg.custom_sound_url ?? "",
    };
    return cachedSettings;
  } catch {
    return {
      notificationEnabled: true,
      soundEnabled: true,
      soundChoice: "default",
      soundVolume: 0.5,
      customSoundUrl: "",
    };
  }
}

/**
 * 模块级 Set，持久化记录已通知过的 Task ID。
 *
 * 使用模块级变量而非组件 ref，确保跨组件挂载/卸载周期保持，
 * 防止用户切换页面后返回时重复通知同一个 Task。
 */
const notifiedTaskIds = new Set<number>();

/**
 * 全局通知服务 Hook
 *
 * 在 App 层挂载，监听 WebSocket 推送的 Task 级事件，
 * 触发系统通知、Toast 提示和音效。
 * 独立于 DownloadPage 运行，确保即使焦点不在下载页面也能收到通知。
 */
export function useNotificationService() {
  const { addToast } = useToastStore();
  const settingsRef = useRef<NotifySettings | null>(null);

  const onMessage = useCallback(
    async (msg: WsMessage) => {
      // 只处理 Task 级事件，忽略逐项进度更新和单项通知
      if (msg.type !== "task_completed" && msg.type !== "task_failed") return;

      const taskId = msg.task_id!;
      // 模块级去重：同一个 Task 只通知一次
      if (notifiedTaskIds.has(taskId)) return;
      notifiedTaskIds.add(taskId);

      // 加载设置（优先使用内存缓存）
      let settings = settingsRef.current;
      if (!settings) {
        settings = await getNotifySettings();
        settingsRef.current = settings;
      }

      const isCompleted = msg.type === "task_completed";
      const count = isCompleted ? msg.completed_count! : msg.failed_count!;
      const total = msg.total_count!;

      // ── 系统通知 ──
      if (settings.notificationEnabled) {
        sendSystemNotification(
          isCompleted ? "下载任务完成" : "下载任务失败",
          isCompleted
            ? `${count}/${total} 项下载成功`
            : `${count}/${total} 项下载失败`,
        );
      }

      // ── Toast 提示 ──
      addToast(
        isCompleted
          ? `任务 #${taskId} 全部完成（${count}/${total}）`
          : `任务 #${taskId} 下载失败（${count}/${total}）`,
        isCompleted ? "success" : "error",
      );

      // ── 音效（只播放一次，不堆叠） ──
      if (settings.soundEnabled) {
        playNotificationSound(isCompleted ? "completed" : "failed", {
          choice: settings.soundChoice,
          volume: settings.soundVolume,
          customUrl:
            settings.soundChoice === "custom"
              ? settings.customSoundUrl || undefined
              : undefined,
          customWavPath:
            settings.soundChoice === "custom_wav"
              ? settings.customSoundUrl || undefined
              : undefined,
        });
      }
    },
    [addToast],
  );

  // 建立独立的 WebSocket 连接，专用于通知
  useWebSocket(onMessage);
}
