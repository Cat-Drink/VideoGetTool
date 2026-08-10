import { useEffect, useState } from "react";
import { Settings, Minus, Square, Maximize2, X } from "lucide-react";
import { usePanelStore } from "../../store/panelStore";

/** 自定义标题栏组件 — 无边框窗口的窗口控制与标题区域 */
export function TitleBar() {
  const [isMaximized, setIsMaximized] = useState(false);
  const { openPanel } = usePanelStore();

  useEffect(() => {
    // 初始化时检查窗口是否已最大化
    import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
      const win = getCurrentWindow();
      win.isMaximized().then(setIsMaximized);
      // 监听最大化状态变化
      const unlisten = win.onResized(() => {
        win.isMaximized().then(setIsMaximized);
      });
      return () => {
        unlisten.then((fn) => fn());
      };
    });
  }, []);

  const handleMinimize = () => {
    import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
      getCurrentWindow().minimize();
    });
  };

  const handleToggleMaximize = () => {
    import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
      getCurrentWindow().toggleMaximize();
    });
  };

  const handleClose = () => {
    import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
      getCurrentWindow().close();
    });
  };

  const handleOpenSettings = () => {
    openPanel("settings");
  };

  return (
    <div
      className="flex items-center h-11 min-h-11 bg-bg-base border-b border-border-light select-none"
      data-tauri-drag-region
    >
      {/* 左侧：应用图标 + 名称 */}
      <div className="flex items-center gap-2 px-4" data-tauri-drag-region>
        <div className="w-7 h-7 rounded-lg bg-purple-500 flex items-center justify-center text-white text-xs font-bold">
          撷
        </div>
        <span className="text-sm font-semibold text-purple-500">撷风拾影</span>
      </div>

      {/* 中间：拖拽区域 */}
      <div className="flex-1 h-full" data-tauri-drag-region />

      {/* 右侧：控制按钮 */}
      <div className="flex items-center h-full" data-tauri-drag-region>
        {/* 设置按钮 */}
        <button
          onClick={handleOpenSettings}
          className="flex items-center justify-center w-11 h-full text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title="设置"
        >
          <Settings size={16} />
        </button>

        {/* 最小化 */}
        <button
          onClick={handleMinimize}
          className="flex items-center justify-center w-11 h-full text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title="最小化"
        >
          <Minus size={16} />
        </button>

        {/* 最大化/还原 */}
        <button
          onClick={handleToggleMaximize}
          className="flex items-center justify-center w-11 h-full text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title={isMaximized ? "还原" : "最大化"}
        >
          {isMaximized ? <Square size={14} /> : <Maximize2 size={14} />}
        </button>

        {/* 关闭 */}
        <button
          onClick={handleClose}
          className="flex items-center justify-center w-11 h-full text-text-secondary hover:bg-error hover:text-white transition-colors"
          title="关闭"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
}