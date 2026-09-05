import { useEffect, useState } from "react";
import {
  Loader2,
  AlertCircle,
  Plus,
  RefreshCw,
  Trash2,
  Download,
  Ban,
  ChevronRight,
  ChevronDown,
} from "lucide-react";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { Badge, badgeTypeLabels } from "../ui/badge";
import { proxyImageUrl } from "../../lib/api";
import { useSubscriptionStore } from "../../store/subscriptionStore";

/** ISO8601 时间戳 → 短格式展示 */
function formatTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const hours = String(d.getHours()).padStart(2, "0");
    const minutes = String(d.getMinutes()).padStart(2, "0");
    return `${month}-${day} ${hours}:${minutes}`;
  } catch {
    return iso;
  }
}

/** 间隔分钟 → 展示文本 */
function formatInterval(minutes: number): string {
  if (minutes >= 24 * 60) {
    return `${Math.round(minutes / (24 * 60))} 天`;
  }
  if (minutes >= 60) {
    return `${Math.round(minutes / 60)} 小时`;
  }
  return `${minutes} 分钟`;
}

export default function SubscriptionPanel() {
  const {
    subscriptions,
    loading,
    error,
    loadSubscriptions,
    addSubscription,
    updateSubscription,
    deleteSubscription,
    scanSubscription,
    newItems,
    itemsLoading,
    loadNewItems,
    acceptItem,
    skipItem,
    skipAllNew,
    scanAndCollect,
  } = useSubscriptionStore();

  // 添加表单
  const [urlInput, setUrlInput] = useState("");
  const [intervalMinutes, setIntervalMinutes] = useState(30);
  const [adding, setAdding] = useState(false);

  // 扫描中 / 处理中的状态（按 id 记录）
  const [scanning, setScanning] = useState<Set<number>>(new Set());
  const [processing, setProcessing] = useState<Set<number>>(new Set());
  // 展开显示新作品的订阅
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  useEffect(() => {
    loadSubscriptions();
  }, [loadSubscriptions]);

  // 监听后台扫描发现新作品的 WebSocket 事件，自动刷新（v0.4.1）
  useEffect(() => {
    const handler = () => {
      loadSubscriptions();
      // 重新加载已展开订阅的新作品列表
      expanded.forEach((subId) => loadNewItems(subId));
    };
    window.addEventListener("vgt:subscription-update", handler);
    return () => window.removeEventListener("vgt:subscription-update", handler);
  }, [expanded, loadSubscriptions, loadNewItems]);

  const handleAdd = async () => {
    if (!urlInput.trim() || adding) return;
    setAdding(true);
    const created = await addSubscription({
      url: urlInput.trim(),
      interval_minutes: intervalMinutes,
    });
    setAdding(false);
    if (created) {
      setUrlInput("");
      // 自动展开新订阅并加载其列表
      setExpanded((prev) => new Set(prev).add(created.id));
      loadNewItems(created.id);
    }
  };

  const handleScan = async (subId: number) => {
    setScanning((prev) => new Set(prev).add(subId));
    const result = await scanSubscription(subId);
    setScanning((prev) => {
      const next = new Set(prev);
      next.delete(subId);
      return next;
    });
    if (result && result.new_count > 0) {
      setExpanded((prev) => new Set(prev).add(subId));
    }
  };

  const handleToggle = async (subId: number, enabled: number) => {
    await updateSubscription(subId, { enabled: enabled === 1 ? 0 : 1 });
  };

  const handleDelete = async (subId: number) => {
    if (!window.confirm("确定删除该订阅及全部作品记录？")) return;
    await deleteSubscription(subId);
  };

  const toggleExpand = (subId: number) => {
    const next = new Set(expanded);
    if (next.has(subId)) {
      next.delete(subId);
    } else {
      next.add(subId);
      if (!newItems[subId]) loadNewItems(subId);
    }
    setExpanded(next);
  };

  const handleAccept = async (subId: number, itemId: number) => {
    setProcessing((prev) => new Set(prev).add(itemId));
    await acceptItem(subId, itemId);
    setProcessing((prev) => {
      const next = new Set(prev);
      next.delete(itemId);
      return next;
    });
  };

  const handleSkip = async (subId: number, itemId: number) => {
    setProcessing((prev) => new Set(prev).add(itemId));
    await skipItem(subId, itemId);
    setProcessing((prev) => {
      const next = new Set(prev);
      next.delete(itemId);
      return next;
    });
  };

  const handleSkipAll = async (subId: number) => {
    if (!window.confirm("确定跳过该订阅的全部新作品？")) return;
    await skipAllNew(subId);
  };

  const handleCollectAll = async (subId: number) => {
    setScanning((prev) => new Set(prev).add(subId));
    await scanAndCollect(subId);
    setScanning((prev) => {
      const next = new Set(prev);
      next.delete(subId);
      return next;
    });
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* 添加订阅表单 */}
      <div className="p-6 pb-3">
        <div className="flex gap-2 items-center">
          <Input
            placeholder="粘贴用户主页链接，例如 https://www.douyin.com/user/xxxxx"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          />
          <select
            className="h-8 px-2 rounded-sm border border-border-default bg-bg-input text-sm text-text-primary outline-none focus:border-purple-500"
            value={intervalMinutes}
            onChange={(e) => setIntervalMinutes(Number(e.target.value))}
            title="扫描间隔"
          >
            {[5, 10, 15, 30, 60, 120, 180, 360, 720, 1440].map((n) => (
              <option key={n} value={n}>
                {formatInterval(n)}
              </option>
            ))}
          </select>
          <Button onClick={handleAdd} disabled={!urlInput.trim() || adding}>
            {adding ? (
              <>
                <Loader2 size={16} className="mr-1 animate-spin" />
                添加中
              </>
            ) : (
              <>
                <Plus size={16} className="mr-1" />
                订阅
              </>
            )}
          </Button>
        </div>
        <p className="mt-2 text-xs text-text-secondary">
          订阅后每 {formatInterval(intervalMinutes)} 自动扫描一次该用户主页，
          发现新作品会出现在下方列表中，可选择下载或跳过。
        </p>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="mx-6 mb-3 p-3 bg-red-50 border border-red-200 rounded-sm">
          <div className="flex items-center gap-2 text-sm text-error">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        </div>
      )}

      <div className="border-t border-border-light" />

      {/* 订阅列表 */}
      <div className="flex-1 overflow-y-auto p-6 pt-4">
        {loading && subscriptions.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-text-disabled">
            <Loader2 size={32} className="mr-3 animate-spin" />
            <span className="text-sm">加载订阅中...</span>
          </div>
        ) : subscriptions.length === 0 ? (
          <div className="text-center py-16 text-text-disabled">
            <div className="text-4xl mb-3 opacity-50">⏰</div>
            <p className="text-sm">还没有订阅，粘贴用户主页链接开始订阅</p>
          </div>
        ) : (
          <div className="space-y-3">
            {subscriptions.map((sub) => {
              const isExpanded = expanded.has(sub.id);
              const items = newItems[sub.id] || [];
              const itemsLoadingFlag = itemsLoading[sub.id];
              const isScanning = scanning.has(sub.id);
              const name = sub.name || sub.url;
              return (
                <div
                  key={sub.id}
                  className="border border-border-light rounded-sm bg-bg-input/50"
                >
                  {/* 订阅头部 */}
                  <div className="flex items-center gap-3 px-4 py-3">
                    <button
                      className="flex-shrink-0 text-text-secondary hover:text-text-primary p-0.5 rounded"
                      onClick={() => toggleExpand(sub.id)}
                      title={isExpanded ? "收起新作品" : "展开新作品"}
                    >
                      {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-text-primary truncate">
                        {name}
                        {sub.id != null && sub.new_count > 0 && (
                          <span className="ml-2 inline-flex items-center rounded-full bg-purple-500 text-white text-xs px-2 py-0.5">
                            {sub.new_count} 新
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-text-secondary mt-0.5 truncate">
                        {sub.url}
                      </div>
                      <div className="text-xs text-text-secondary mt-0.5">
                        每 {formatInterval(sub.interval_minutes)} 扫描一次 ·
                        上次扫描 {formatTime(sub.last_scan_at)}
                        {sub.last_scan_status === "error" && (
                          <span className="text-error ml-1">
                            （失败{sub.last_scan_error ? `: ${sub.last_scan_error}` : ""}）
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                        sub.enabled === 1 ? "bg-purple-500" : "bg-bg-gray"
                      }`}
                      onClick={() => handleToggle(sub.id, sub.enabled)}
                      title={sub.enabled === 1 ? "停用订阅" : "启用订阅"}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          sub.enabled === 1 ? "translate-x-4" : "translate-x-0.5"
                        }`}
                      />
                    </button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={isScanning}
                      onClick={() => handleScan(sub.id)}
                      title="立即扫描"
                    >
                      {isScanning ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <RefreshCw size={14} />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-warning"
                      onClick={() => handleDelete(sub.id)}
                      title="删除订阅"
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>

                  {/* 新作品列表 */}
                  {isExpanded && (
                    <div className="border-t border-border-light px-4 py-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs text-text-secondary">
                          新作品 {items.length} 个
                          {itemsLoadingFlag && (
                            <Loader2 size={12} className="inline ml-1 animate-spin" />
                          )}
                        </span>
                        <div className="flex gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={items.length === 0}
                            onClick={() => handleCollectAll(sub.id)}
                            title="扫描并入队全部新作品"
                          >
                            <Download size={14} className="mr-1" />
                            全部下载
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-warning"
                            disabled={items.length === 0}
                            onClick={() => handleSkipAll(sub.id)}
                          >
                            <Ban size={14} className="mr-1" />
                            全部跳过
                          </Button>
                        </div>
                      </div>

                      {itemsLoadingFlag && items.length === 0 ? (
                        <div className="py-4 text-center text-text-disabled text-xs">
                          加载中...
                        </div>
                      ) : items.length === 0 ? (
                        <div className="py-4 text-center text-text-disabled text-xs">
                          暂无新作品，点击右上角刷新图标立即扫描
                        </div>
                      ) : (
                        <div className="divide-y divide-border-light">
                          {items.map((item) => {
                            const isProcessing = processing.has(item.id);
                            const typeLabel =
                              (badgeTypeLabels as Record<string, string>)[item.type] || "未知";
                            const variant =
                              item.type === "image_set"
                                ? "image_set"
                                : item.type === "long_video"
                                  ? "long_video"
                                  : "video";
                            return (
                              <div key={item.id} className="flex items-center gap-3 py-2">
                                <div className="w-12 h-12 rounded-sm bg-bg-hover flex-shrink-0 flex items-center justify-center text-text-disabled text-xs overflow-hidden">
                                  {item.cover_url ? (
                                    <img
                                      src={proxyImageUrl(item.cover_url)}
                                      alt={item.title || ""}
                                      className="w-full h-full object-cover"
                                    />
                                  ) : (
                                    "封面"
                                  )}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm text-text-primary truncate">
                                    {item.title || "未知作品"}
                                  </div>
                                  <div className="text-xs text-text-secondary mt-0.5 truncate">
                                    @{item.author || "未知作者"} · 发布于{" "}
                                    {formatTime(item.publish_time)}
                                  </div>
                                </div>
                                <Badge variant={variant} />
                                <span className="text-xs text-text-secondary w-12 text-right flex-shrink-0">
                                  {item.duration || (item.image_count ? `${item.image_count}张` : "")}
                                </span>
                                <span className="text-xs text-text-secondary w-16 flex-shrink-0">
                                  {typeLabel}
                                </span>
                                <Button
                                  variant="primary"
                                  size="sm"
                                  disabled={isProcessing}
                                  onClick={() => handleAccept(sub.id, item.id)}
                                  title="下载该作品"
                                >
                                  {isProcessing ? (
                                    <Loader2 size={14} className="animate-spin" />
                                  ) : (
                                    <Download size={14} className="mr-1" />
                                  )}
                                  下载
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="text-warning"
                                  disabled={isProcessing}
                                  onClick={() => handleSkip(sub.id, item.id)}
                                  title="跳过该作品"
                                >
                                  跳过
                                </Button>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}