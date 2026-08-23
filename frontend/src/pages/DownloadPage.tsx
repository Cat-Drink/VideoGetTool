import { useEffect, useCallback, useRef } from "react";
import { Search, RefreshCw } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { TaskItem } from "../components/app/TaskItem";
import { useTaskStore } from "../store/taskStore";
import { useWebSocket } from "../hooks/useWebSocket";
import { useToastStore } from "../store/toastStore";
import { useUiInputStore } from "../store/uiInputStore";
import * as api from "../lib/api";
import { useNavigate } from "react-router-dom";
import type { WsMessage } from "../hooks/useWebSocket";
import { playNotificationSound } from "../lib/sound";
import { sendSystemNotification } from "../lib/notify";

/** 从配置加载的通知设置缓存 */
interface NotifySettings {
  notificationEnabled: boolean;
  soundEnabled: boolean;
  soundChoice: "default" | "soft" | "cheerful" | "custom";
  soundVolume: number;
  customSoundUrl: string;
}

/** 读取通知配置（失败时返回默认值） */
async function loadNotifySettings(): Promise<NotifySettings> {
  try {
    const cfg = await api.fetchConfig();
    return {
      notificationEnabled: cfg.notification_enabled,
      soundEnabled: cfg.sound_enabled,
      soundChoice: cfg.sound_choice as NotifySettings["soundChoice"],
      soundVolume: cfg.sound_volume,
      customSoundUrl: cfg.custom_sound_url ?? "",
    };
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

export default function DownloadPage() {
  const navigate = useNavigate();
  const { downloadSearch: search, setDownloadSearch: setSearch } = useUiInputStore();
  const {
    items, loading, error,
    loadTasks, applyProgressUpdate,
    pauseItem, resumeItem, retryItem, retryAllFailed, pauseAll, resumeAll, clearCompleted,
    verifyFiles,
  } = useTaskStore();
  const { addToast } = useToastStore();
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevStatusRef = useRef<Map<number, string>>(new Map());
  const notifiedTaskRef = useRef<Set<number>>(new Set());

  const handleDeleteItem = async (itemId: number) => {
    try {
      await api.deleteTaskItem(itemId);
      await loadTasks();
    } catch (e) {
      addToast("删除失败", "error");
    }
  };

  // 加载任务数据
  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  // WebSocket 消息处理
  const onWsMessage = useCallback(
    async (msg: WsMessage) => {
      // 处理 Task 级完成/失败事件（聚合通知）
      if (msg.type === "task_completed") {
        const task_id = msg.task_id!;
        const completed_count = msg.completed_count!;
        const total_count = msg.total_count!;
        // 避免重复通知同一个 Task
        if (notifiedTaskRef.current.has(task_id)) return;
        notifiedTaskRef.current.add(task_id);

        const settings = await loadNotifySettings();

        // 系统通知
        if (settings.notificationEnabled) {
          sendSystemNotification(
            "下载任务完成",
            `任务 #${task_id}：${completed_count}/${total_count} 项下载成功`,
          );
        }
        // Toast 通知
        addToast(`任务 #${task_id} 全部完成（${completed_count}/${total_count}）`, "success");
        // 音效
        if (settings.soundEnabled) {
          playNotificationSound("completed", {
            choice: settings.soundChoice,
            volume: settings.soundVolume,
            customUrl: settings.customSoundUrl || undefined,
          });
        }
        return;
      }

      if (msg.type === "task_failed") {
        const task_id = msg.task_id!;
        const failed_count = msg.failed_count!;
        const total_count = msg.total_count!;
        if (notifiedTaskRef.current.has(task_id)) return;
        notifiedTaskRef.current.add(task_id);

        const settings = await loadNotifySettings();

        if (settings.notificationEnabled) {
          sendSystemNotification(
            "下载任务失败",
            `任务 #${task_id}：${failed_count}/${total_count} 项下载失败`,
          );
        }
        addToast(`任务 #${task_id} 下载失败（${failed_count}/${total_count}）`, "error");
        if (settings.soundEnabled) {
          playNotificationSound("failed", {
            choice: settings.soundChoice,
            volume: settings.soundVolume,
            customUrl: settings.customSoundUrl || undefined,
          });
        }
        return;
      }

      // 处理逐项进度更新（保留原有逻辑）
      if (msg.type === "progress" && msg.updates) {
        for (const update of msg.updates) {
          const prevStatus = prevStatusRef.current.get(update.task_item_id);
          const newStatus = update.status;
          const isTerminal = (s: string) => s === "completed" || s === "failed";

          if (prevStatus && !isTerminal(prevStatus) && isTerminal(newStatus)) {
            playNotificationSound(newStatus as "completed" | "failed");
            addToast(
              newStatus === "completed" ? "任务下载完成" : "任务下载失败",
              newStatus === "completed" ? "success" : "error",
            );
          }

          prevStatusRef.current.set(update.task_item_id, newStatus);
          applyProgressUpdate(update);
        }
      }
    },
    [applyProgressUpdate, addToast],
  );

  const { connected } = useWebSocket(onWsMessage);

  // WebSocket 断开时降级为轮询 REST API（每 2 秒）
  useEffect(() => {
    if (connected) {
      // 已连接，清除轮询定时器
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    } else {
      // 未连接，启动轮询（除非已有定时器）
      if (!pollTimerRef.current) {
        pollTimerRef.current = setInterval(() => {
          loadTasks();
        }, 2000);
      }
    }
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [connected, loadTasks]);

  // 过滤
  const filtered = items.filter(
    (t) =>
      t.title.toLowerCase().includes(search.toLowerCase()) ||
      t.author.toLowerCase().includes(search.toLowerCase()),
  );

  // 统计
  const stats = {
    total: items.length,
    downloading: items.filter((t) => t.status === "downloading").length,
    completed: items.filter((t) => t.status === "completed").length,
    failed: items.filter((t) => t.status === "failed").length,
  };

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-6 h-12 border-b border-border-light">
        <Button variant="ghost" size="sm" onClick={pauseAll}>全部暂停</Button>
        <Button variant="ghost" size="sm" onClick={resumeAll}>全部开始</Button>
        <Button variant="ghost" size="sm" className="text-error" onClick={clearCompleted}>清空已完成</Button>
        {stats.failed > 0 && (
          <Button variant="ghost" size="sm" className="text-warning" onClick={retryAllFailed}>
            全部失败重试
          </Button>
        )}
        {stats.completed > 0 && (
          <Button variant="ghost" size="sm" onClick={async () => {
            const result = await verifyFiles();
            if (result.missing_count > 0) {
              addToast(`发现 ${result.missing_count} 个文件缺失，已标记为失败`, "warning");
            } else {
              addToast("所有已完成文件均存在", "success");
            }
          }}>
            校验文件
          </Button>
        )}
        <div className="flex-1" />
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-3 text-xs text-text-secondary mr-2">
            <span>总数 {stats.total}</span>
            {stats.downloading > 0 && <span className="text-purple-500">下载中 {stats.downloading}</span>}
            {stats.completed > 0 && <span className="text-success">已完成 {stats.completed}</span>}
            {stats.failed > 0 && <span className="text-error">失败 {stats.failed}</span>}
          </div>
          <div className="relative w-48">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-disabled" />
            <Input
              placeholder="搜索任务..."
              className="pl-8 h-7 text-xs"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="mx-6 mt-3 p-3 bg-red-50 border border-red-200 rounded-sm">
          <div className="flex items-center gap-2 text-sm text-error">
            <span>⚠</span>
            <span>{error}</span>
            <Button variant="ghost" size="sm" onClick={loadTasks} className="ml-auto">
              重试
            </Button>
          </div>
        </div>
      )}

      {/* Task List */}
      <div className="flex-1 overflow-y-auto">
        {loading && items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-text-disabled">
            <RefreshCw size={32} className="animate-spin mb-3" />
            <p className="text-sm">正在加载任务列表...</p>
          </div>
        ) : filtered.length === 0 && !error ? (
          <div className="flex flex-col items-center justify-center h-full text-text-disabled">
            <div className="text-4xl mb-3">📥</div>
            <p className="text-base font-medium text-text-primary">
              {search ? "没有匹配的任务" : "还没有下载任务"}
            </p>
            <p className="text-sm mt-1">
              {search ? "试试其他关键词" : "前往链接抓取页添加链接"}
            </p>
            {!search && (
              <Button className="mt-4" size="sm" onClick={() => navigate("/batch-fetch")}>
                去添加链接
              </Button>
            )}
          </div>
        ) : (
          <div>
            {filtered.map((task) => (
              <TaskItem
                key={task.id}
                task={task}
                onPause={pauseItem}
                onResume={resumeItem}
                onRetry={retryItem}
                onDelete={handleDeleteItem}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}