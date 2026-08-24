/** 任务状态管理 - Zustand Store */

import { create } from "zustand";
import type { TaskItemResponse } from "../lib/api";
import * as api from "../lib/api";

/** 前端展示用的任务项 */
export interface DisplayTask {
  id: number;
  taskId: number;
  awemeId: string;
  title: string;
  author: string;
  type: "video" | "image_set" | "long_video";
  duration: string;
  imageCount: number;
  coverUrl: string;
  status: api.TaskStatus;
  progress: number;
  downloadedBytes: number;
  totalBytes: number;
  failReason?: string;
  localPath?: string;
  createdAt: string;
}

function mapTaskItem(item: TaskItemResponse): DisplayTask {
  return {
    id: item.id ?? 0,
    taskId: item.task_id,
    awemeId: item.aweme_id ?? "",
    title: item.title ?? "",
    author: item.author ?? "",
    type: (item.type as DisplayTask["type"]) || "video",
    duration: "",
    imageCount: 0,
    coverUrl: item.cover_url || "",
    status: item.status as api.TaskStatus,
    progress: item.progress,
    downloadedBytes: item.downloaded_bytes,
    totalBytes: item.total_bytes,
    failReason: item.fail_reason ?? undefined,
    localPath: item.local_path ?? undefined,
    createdAt: "",
  };
}

interface TaskStore {
  /** 展平后的所有任务项 */
  items: DisplayTask[];
  /** 服务端任务列表 */
  tasks: api.TaskResponse[];
  /** 加载状态 */
  loading: boolean;
  /** 错误信息 */
  error: string | null;
  /** 上次校验时间 */
  lastVerifiedAt: string | null;

  /** 从 API 加载任务数据 */
  loadTasks: () => Promise<void>;
  /** 应用 WebSocket 进度更新 */
  applyProgressUpdate: (update: { task_item_id: number; progress: number; status: string; downloaded_bytes: number; total_bytes: number }) => void;
  /** 暂停单项 */
  pauseItem: (itemId: number) => Promise<void>;
  /** 恢复单项 */
  resumeItem: (itemId: number) => Promise<void>;
  /** 重新执行单项 */
  retryItem: (itemId: number) => Promise<void>;
  /** 全部失败重试 */
  retryAllFailed: () => Promise<void>;
  /** 全部暂停 */
  pauseAll: () => Promise<void>;
  /** 全部恢复 */
  resumeAll: () => Promise<void>;
  /** 清空已完成 */
  clearCompleted: () => Promise<void>;
  /** 校验已完成文件是否存在 */
  verifyFiles: () => Promise<{ missing_count: number }>;
}

export const useTaskStore = create<TaskStore>((set, get) => ({
  items: [],
  tasks: [],
  loading: false,
  error: null,
  lastVerifiedAt: null,

	  loadTasks: async () => {
    set({ loading: true, error: null });
    try {
      const tasks = await api.fetchTasks();
      // 加载每个任务的 items
      const freshItems: DisplayTask[] = [];
      for (const task of tasks) {
        try {
          const items = await api.fetchTaskItems(task.id);
          freshItems.push(...items.map(mapTaskItem));
        } catch {
          // 单个任务加载失败不阻断整体
        }
      }

      // 合并：以 API 数据为权威源，保留更高进度/终态的项，避免闪烁与状态回退
      set((state) => {
        const existingMap = new Map(state.items.map((i) => [i.id, i]));
        const merged: DisplayTask[] = freshItems.map((fresh) => {
          const existing = existingMap.get(fresh.id);
          if (!existing) return fresh;

          // 已有项是终态（completed/failed）时保留，避免 API 延迟导致状态回退
          const isTerminal = (s: api.TaskStatus) => s === "completed" || s === "failed";
          if (isTerminal(existing.status) && !isTerminal(fresh.status)) {
            return existing;
          }
          // 本地进度更高且状态相同，保留本地以免闪烁
          if (existing.progress > fresh.progress && existing.status === fresh.status) {
            return existing;
          }
          return fresh;
        });
        return { items: merged.sort((a, b) => b.id - a.id), tasks, loading: false };
      });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "加载任务失败", loading: false });
    }
  },

  applyProgressUpdate: (update) => {
	    set((state) => ({
	      items: state.items.map((item) =>
	        item.id === update.task_item_id
	          ? {
              ...item,
              progress: update.status === "completed" || update.status === "processing" ? 100 : update.progress,
              status: update.status as api.TaskStatus,
              downloadedBytes: update.downloaded_bytes,
              totalBytes: update.total_bytes,
            }
	          : item,
	      ),
	    }));
	  },

  pauseItem: async (itemId) => {
    try {
      await api.pauseDownload(itemId);
      set((state) => ({
        items: state.items.map((item) =>
          item.id === itemId ? { ...item, status: "paused" } : item,
        ),
      }));
    } catch (e) {
      console.error("暂停失败:", e);
    }
  },

  resumeItem: async (itemId) => {
    try {
      await api.resumeDownload(itemId);
      set((state) => ({
        items: state.items.map((item) =>
          item.id === itemId ? { ...item, status: "downloading" } : item,
        ),
      }));
    } catch (e) {
      console.error("恢复失败:", e);
    }
  },

  retryItem: async (itemId) => {
    try {
      // 先本地立即更新状态为 pending，进度置 0，提升用户体验
      set((state) => ({
        items: state.items.map((item) =>
          item.id === itemId
            ? { ...item, status: "pending", progress: 0, downloadedBytes: 0, totalBytes: 0 }
            : item,
        ),
      }));
      await api.retryDownload(itemId);
      // 不立即 loadTasks，等待 WebSocket 推送更新
      // 但如果 WebSocket 断开，3 秒后会由轮询机制自动刷新
    } catch (e) {
      console.error("重新执行失败:", e);
      // 失败时还原真实状态
      await get().loadTasks();
    }
  },

  retryAllFailed: async () => {
    try {
      // 本地立即将所有 failed 项置为 pending
      set((state) => ({
        items: state.items.map((item) =>
          item.status === "failed"
            ? { ...item, status: "pending", progress: 0, downloadedBytes: 0, totalBytes: 0 }
            : item,
        ),
      }));
      await api.retryAllFailed();
      // 等待 WebSocket 推送或轮询更新
    } catch (e) {
      console.error("全部失败重试失败:", e);
      await get().loadTasks();
    }
  },

  pauseAll: async () => {
    try {
      await api.pauseAll();
      await get().loadTasks();
    } catch (e) {
      console.error("全部暂停失败:", e);
    }
  },

  resumeAll: async () => {
    try {
      await api.resumeAll();
      await get().loadTasks();
    } catch (e) {
      console.error("全部恢复失败:", e);
    }
  },

  clearCompleted: async () => {
    try {
      await api.clearCompleted();
      await get().loadTasks();
    } catch (e) {
      console.error("清空失败:", e);
    }
  },

  verifyFiles: async () => {
    try {
      const result = await api.verifyCompletedFiles();
      set({ lastVerifiedAt: new Date().toISOString() });
      // 如果有缺失文件，刷新列表以更新状态
      if (result.missing_count > 0) {
        await get().loadTasks();
      }
      return result;
    } catch (e) {
      console.error("文件校验失败:", e);
      return { missing_count: 0 };
    }
  },
}));