/** 订阅模式状态管理 - Zustand Store（v0.5.0） */

import { create } from "zustand";
import * as api from "../lib/api";

interface SubscriptionStore {
  // 订阅列表
  subscriptions: api.SubscriptionResponse[];
  loading: boolean;
  error: string | null;

  // 各订阅的新作品列表（subscription_id → items）
  newItems: Record<number, api.SubscriptionItemResponse[]>;
  itemsLoading: Record<number, boolean>;

  /** 加载订阅列表 */
  loadSubscriptions: () => Promise<void>;
  /** 添加订阅 */
  addSubscription: (params: {
    url: string;
    name?: string;
    interval_minutes?: number;
  }) => Promise<api.SubscriptionResponse | null>;
  /** 更新订阅（启用/间隔/名称） */
  updateSubscription: (
    subId: number,
    params: { name?: string; interval_minutes?: number; enabled?: number },
  ) => Promise<void>;
  /** 删除订阅 */
  deleteSubscription: (subId: number) => Promise<void>;
  /** 立即扫描 */
  scanSubscription: (subId: number) => Promise<api.ScanResultResponse | null>;
  /** 加载某订阅的新作品 */
  loadNewItems: (subId: number) => Promise<void>;
  /** 接受（下载）单个新作品 */
  acceptItem: (subId: number, itemId: number) => Promise<void>;
  /** 跳过单个新作品 */
  skipItem: (subId: number, itemId: number) => Promise<void>;
  /** 跳过某订阅全部新作品 */
  skipAllNew: (subId: number) => Promise<void>;
  /** 扫描并全部入队下载 */
  scanAndCollect: (subId: number) => Promise<{ queued: number } | null>;
  /** 清空错误 */
  clearError: () => void;
}

export const useSubscriptionStore = create<SubscriptionStore>((set, get) => ({
  subscriptions: [],
  loading: false,
  error: null,
  newItems: {},
  itemsLoading: {},

  loadSubscriptions: async () => {
    set({ loading: true, error: null });
    try {
      const subs = await api.fetchSubscriptions();
      set({ subscriptions: subs, loading: false });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "加载订阅失败", loading: false });
    }
  },

  addSubscription: async (params) => {
    set({ error: null });
    try {
      const created = await api.addSubscription(params);
      // 重新拉取列表以拿到 new_count
      await get().loadSubscriptions();
      return created;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "添加订阅失败" });
      return null;
    }
  },

  updateSubscription: async (subId, params) => {
    set({ error: null });
    try {
      await api.updateSubscription(subId, params);
      await get().loadSubscriptions();
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "更新订阅失败" });
    }
  },

  deleteSubscription: async (subId) => {
    set({ error: null });
    try {
      await api.deleteSubscription(subId);
      set((state) => {
        const newItems = { ...state.newItems };
        delete newItems[subId];
        const itemsLoading = { ...state.itemsLoading };
        delete itemsLoading[subId];
        return { newItems, itemsLoading };
      });
      await get().loadSubscriptions();
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "删除订阅失败" });
    }
  },

  scanSubscription: async (subId) => {
    set({ error: null });
    try {
      const result = await api.scanSubscription(subId);
      await get().loadSubscriptions();
      if (result && result.new_count > 0) {
        await get().loadNewItems(subId);
      }
      return result;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "扫描失败" });
      return null;
    }
  },

  loadNewItems: async (subId) => {
    set((state) => ({
      itemsLoading: { ...state.itemsLoading, [subId]: true },
    }));
    try {
      const items = await api.fetchSubscriptionItems(subId, "new");
      set((state) => ({
        newItems: { ...state.newItems, [subId]: items },
        itemsLoading: { ...state.itemsLoading, [subId]: false },
      }));
    } catch (e) {
      set((state) => ({
        itemsLoading: { ...state.itemsLoading, [subId]: false },
        error: e instanceof Error ? e.message : "加载新作品失败",
      }));
    }
  },

  acceptItem: async (subId, itemId) => {
    try {
      await api.acceptSubscriptionItem(itemId);
      await get().loadNewItems(subId);
      await get().loadSubscriptions();
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "入队下载失败" });
    }
  },

  skipItem: async (subId, itemId) => {
    try {
      await api.skipSubscriptionItem(itemId);
      await get().loadNewItems(subId);
      await get().loadSubscriptions();
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "跳过失败" });
    }
  },

  skipAllNew: async (subId) => {
    try {
      await api.skipAllNewItems(subId);
      await get().loadNewItems(subId);
      await get().loadSubscriptions();
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "跳过失败" });
    }
  },

  scanAndCollect: async (subId) => {
    set({ error: null });
    try {
      const result = await api.scanAndCollect(subId);
      await get().loadSubscriptions();
      await get().loadNewItems(subId);
      return result;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "扫描并下载失败" });
      return null;
    }
  },

  clearError: () => set({ error: null }),
}));
