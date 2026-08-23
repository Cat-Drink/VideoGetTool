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

  // WebSocket 进度更新
  const onWsMessage = useCallback(
    (msg: WsMessage) => {
      if (msg.type === "progress" && msg.updates) {
        for (const update of msg.updates) {
          applyProgressUpdate(update);
        }
      }
    },
    [applyProgressUpdate],
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