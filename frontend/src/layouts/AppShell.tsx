import { NavBar } from "../components/NavBar";
import { TitleBar } from "../components/app/TitleBar";
import { SlidePanel } from "../components/app/SlidePanel";
import SettingsPanel from "../components/app/SettingsPanel";
import CookiePanel from "../components/app/CookiePanel";
import { Outlet } from "react-router-dom";
import { usePanelStore } from "../store/panelStore";

export function AppShell() {
  const { activePanel, closePanel } = usePanelStore();

  return (
    <div className="flex flex-col h-full w-full bg-bg-base overflow-hidden transition-colors">
      <TitleBar />
      <div className="flex flex-1 overflow-hidden">
        <NavBar />
        <main className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>

      {/* 侧滑面板 */}
      <SlidePanel
        open={activePanel === "settings"}
        title="设置"
        onClose={closePanel}
      >
        <SettingsPanel />
      </SlidePanel>
      <SlidePanel
        open={activePanel === "cookie"}
        title="Cookie 配置"
        onClose={closePanel}
      >
        <CookiePanel />
      </SlidePanel>
    </div>
  );
}