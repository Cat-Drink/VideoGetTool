import { useEffect, useState } from "react";
import { Settings, Minus, Square, Maximize2, X, Moon, Sun } from "lucide-react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { usePanelStore } from "../../store/panelStore";
import { useThemeStore } from "../../store/themeStore";

/** 自定义标题栏组件 — 纯无边框窗口的窗口控制与标题区域 */
export function TitleBar() {
  const [isMaximized, setIsMaximized] = useState(false);
  const [appWindow, setAppWindow] = useState<ReturnType<typeof getCurrentWindow> | null>(null);
  const { openPanel } = usePanelStore();
  const { theme, toggleTheme } = useThemeStore();

  useEffect(() => {
    try {
      const window = getCurrentWindow();
      setAppWindow(window);
      // 读取窗口当前最大化状态
      window.isMaximized().then(setIsMaximized);
      // 监听窗口尺寸变化，同步最大化/还原图标
      const unlisten = window.onResized(() => {
        window.isMaximized().then(setIsMaximized);
      });
      return () => {
        unlisten.then((fn) => fn());
      };
    } catch {
      // 浏览器开发环境没有 Tauri 窗口 API，保持无窗口控制状态
      return undefined;
    }
  }, []);

  const handleMinimize = () => {
    appWindow?.minimize();
  };

  const handleToggleMaximize = () => {
    appWindow?.toggleMaximize();
  };

  const handleClose = () => {
    appWindow?.close();
  };

  const handleOpenSettings = () => {
    openPanel("settings");
  };

  return (
    <div className="flex items-center h-9 min-h-9 bg-bg-base select-none">
      {/* 左侧：应用图标 + 名称（可拖拽区域） */}
      <div className="flex items-center gap-2 px-4 h-full" data-tauri-drag-region>
        <div className="w-6 h-6 rounded-md bg-purple-500 flex items-center justify-center text-white text-xs font-bold">
          撷
        </div>
        <span className="text-sm font-semibold text-purple-500">撷风拾影</span>
      </div>

      {/* 中间：弹性拖拽区域（不包含右侧按钮，按钮无需 pointer-events hack） */}
      <div className="flex-1 h-full" data-tauri-drag-region />

      {/* 右侧：控制按钮（不在拖拽区域内，点击事件自然触发） */}
      <div className="flex items-center h-full">
        {/* 深色/浅色模式切换 */}
        <button
          onClick={toggleTheme}
          className="flex items-center justify-center w-10 h-full text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
        >
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>

        {/* 设置 */}
        <button
          onClick={handleOpenSettings}
          className="flex items-center justify-center w-10 h-full text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title="设置"
        >
          <Settings size={15} />
        </button>

        {/* 最小化 */}
        <button
          onClick={handleMinimize}
          className="flex items-center justify-center w-10 h-full text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title="最小化"
        >
          <Minus size={15} />
        </button>

        {/* 最大化/还原 */}
        <button
          onClick={handleToggleMaximize}
          className="flex items-center justify-center w-10 h-full text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title={isMaximized ? "还原" : "最大化"}
        >
          {isMaximized ? <Square size={13} /> : <Maximize2 size={13} />}
        </button>

        {/* 关闭 */}
        <button
          onClick={handleClose}
          className="flex items-center justify-center w-10 h-full text-text-secondary hover:bg-error hover:text-white transition-colors"
          title="关闭"
        >
          <X size={15} />
        </button>
      </div>
    </div>
  );
}