import { create } from "zustand";

type PanelId = "settings" | "cookie" | null;

interface PanelState {
  activePanel: PanelId;
  openPanel: (panel: Exclude<PanelId, null>) => void;
  closePanel: () => void;
}

/** 侧滑面板（设置 / Cookie）开关状态 */
export const usePanelStore = create<PanelState>((set) => ({
  activePanel: null,
  openPanel: (panel) => set({ activePanel: panel }),
  closePanel: () => set({ activePanel: null }),
}));