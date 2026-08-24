import { ReactNode } from "react";
import { ArrowLeft, X } from "lucide-react";
import { cn } from "../../lib/utils";

interface SlidePanelProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

/** 从右侧滑入的覆盖层面板（设置 / Cookie 共用） */
export function SlidePanel({ open, title, onClose, children }: SlidePanelProps) {
  return (
    <>
      {/* 全屏覆盖面板（从右侧滑入，覆盖整个窗口） */}
      <aside
        className={cn(
          "fixed inset-0 z-50 bg-bg-base flex flex-col transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        {/* 顶部导航栏 */}
        <div className="flex items-center justify-between px-4 h-12 bg-bg-base border-b border-border-light">
          <button
            onClick={onClose}
            className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors"
          >
            <ArrowLeft size={16} /> 返回
          </button>
          <h1 className="text-display font-semibold text-text-primary absolute left-1/2 -translate-x-1/2">{title}</h1>
          <button
            onClick={onClose}
            className="flex items-center justify-center w-8 h-8 text-text-secondary hover:text-text-primary hover:bg-bg-hover rounded-md transition-colors"
            title="关闭"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </aside>
    </>
  );
}