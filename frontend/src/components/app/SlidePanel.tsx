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
      {/* 侧滑面板 */}
      <aside
        className={cn(
          "fixed top-0 right-0 z-50 h-full w-[520px] max-w-full bg-bg-base shadow-overlay flex flex-col transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <div className="flex items-center gap-3 px-4 h-14 border-b border-border-light">
          <button
            onClick={onClose}
            className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors"
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