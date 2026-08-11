import { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
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
      {/* 半透明覆盖层 */}
      <div
        className={cn(
          "fixed inset-0 z-40 bg-black/40 transition-opacity duration-300",
          open ? "opacity-100" : "opacity-0 pointer-events-none",
        )}
        onClick={onClose}
      />
      {/* 侧滑面板（从标题栏下方开始，不遮盖 36px 标题栏） */}
      <aside
        className={cn(
          "fixed top-9 right-0 z-50 h-[calc(100%-36px)] w-[520px] max-w-full bg-bg-base flex flex-col transition-transform duration-300 ease-out",
          open ? "translate-x-0 shadow-overlay" : "translate-x-full shadow-none",
        )}
      >
        <div className="flex items-center gap-3 px-4 h-12">
          <button
            onClick={onClose}
            className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors"
            style={{ pointerEvents: "auto" }}
          >
            <ArrowLeft size={16} /> 返回
          </button>
          <h1 className="text-display font-semibold text-text-primary">{title}</h1>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </aside>
    </>
  );
}