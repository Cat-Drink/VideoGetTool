import { Play, Pause, RotateCw, FolderOpen, RefreshCw, Trash2 } from "lucide-react";
import { openInFolder } from "../../lib/tauri";
import { proxyImageUrl } from "../../lib/api";
import { Progress } from "../ui/progress";
import { Badge } from "../ui/badge";
import type { DisplayTask } from "../../store/taskStore";

interface TaskItemProps {
  task: DisplayTask;
  onPause?: (id: number) => void;
  onResume?: (id: number) => void;
  onRetry?: (id: number) => void;
  onDelete?: (id: number) => void;
}

const statusConfig = {
  pending: { label: "等待中", progressVariant: "default" as const, actionIcon: null },
  downloading: { label: "下载中", progressVariant: "default" as const, actionIcon: <Pause size={14} /> },
  paused: { label: "已暂停", progressVariant: "paused" as const, actionIcon: <Play size={14} /> },
  processing: { label: "处理中", progressVariant: "default" as const, actionIcon: null },
  completed: { label: "完成", progressVariant: "success" as const, actionIcon: <FolderOpen size={14} /> },
  failed: { label: "失败", progressVariant: "error" as const, actionIcon: <RefreshCw size={14} /> },
};

export function TaskItem({ task, onPause, onResume, onRetry, onDelete }: TaskItemProps) {
  const config = statusConfig[task.status];
  const isFailed = task.status === "failed";
  const typeBadgeVariant = task.type === "video" ? "video" : task.type === "image_set" ? "image_set" : "long_video" as const;

  const handleAction = () => {
    if (task.status === "downloading" && onPause) onPause(task.id);
    else if (task.status === "paused" && onResume) onResume(task.id);
  };

  return (
    <div className={`flex items-center gap-3 px-6 py-3 border-b border-border-light hover:bg-bg-hover transition-colors ${isFailed ? "border-l-3 border-l-error" : ""}`}>
      {/* Thumbnail */}
      <div className="w-16 h-16 rounded-sm bg-bg-hover flex-shrink-0 flex items-center justify-center text-text-disabled text-xs">
        {task.coverUrl ? (
          <img src={proxyImageUrl(task.coverUrl)} alt={task.title} className="w-full h-full object-cover rounded-sm" />
        ) : (
          <div className="flex flex-col items-center">
            <span className="text-lg">📄</span>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          {/* 标题占满剩余宽度并截断，标签固定在右侧同一位置，不随标题长度漂移 */}
          <span className="flex-1 min-w-0 truncate text-sm font-semibold text-text-primary">{task.title || task.awemeId || `任务 #${task.id}`}</span>
          <Badge variant={typeBadgeVariant} />
        </div>
        <div className="flex items-center gap-2 mt-0.5 text-xs text-text-secondary">
          <span>@{task.author || "未知作者"}</span>
          <span>·</span>
          <span>{task.duration || (task.imageCount ? `${task.imageCount}张图` : task.type === "image_set" ? "图集" : "")}</span>
        </div>
        {isFailed && task.failReason && (
          <div className="mt-1 text-xs text-error">⚠ {task.failReason}</div>
        )}
      </div>

      {/* Progress */}
      <div className="w-44 flex-shrink-0">
        {/* 失败项进度为 0，红色条不可见；显示满格红色以清晰标识失败状态 */}
        <Progress
          value={task.status === "failed" ? 100 : task.progress}
          variant={config.progressVariant}
        />
        <div className="text-xs text-text-secondary text-center mt-0.5">
          {task.status === "completed" ? "完成" : task.status === "failed" ? "失败" : task.status === "paused" ? "已暂停" : task.status === "processing" ? "处理中" : `${Math.round(task.progress)}%`}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        {/* 暂停/恢复（仅下载中/已暂停显示） */}
        {(task.status === "downloading" || task.status === "paused") && (
          <button
            onClick={handleAction}
            className="w-8 h-8 flex items-center justify-center rounded-sm text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
            title={task.status === "downloading" ? "暂停" : "恢复"}
          >
            {config.actionIcon}
          </button>
        )}
        {/* 打开所在文件夹（仅已完成显示） */}
        {task.status === "completed" && task.localPath && (
          <button
            onClick={() => openInFolder(task.localPath!)}
            className="w-8 h-8 flex items-center justify-center rounded-sm text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
            title="打开所在文件夹"
          >
            <FolderOpen size={14} />
          </button>
        )}
        {/* 重新执行 */}
        <button
          onClick={() => onRetry?.(task.id)}
          className="w-8 h-8 flex items-center justify-center rounded-sm text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title="重新执行"
        >
          <RotateCw size={14} />
        </button>
        {/* 删除任务 */}
        {onDelete && (
          <button
            onClick={() => onDelete(task.id)}
            className="w-8 h-8 flex items-center justify-center rounded-sm text-text-secondary hover:bg-bg-hover hover:text-error transition-colors"
            title="删除任务"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </div>
  );
}