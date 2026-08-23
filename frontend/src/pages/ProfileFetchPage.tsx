import { useState } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { useParseStore } from "../store/parseStore";
import { useUiInputStore } from "../store/uiInputStore";

/** ISO8601 时间戳 → 短格式展示 */
function formatTime(iso: string): string {
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

export default function ProfileFetchPage() {
  const { profileHomeUrl: homeUrl, setProfileHomeUrl: setHomeUrl } = useUiInputStore();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [typeFilter, setTypeFilter] = useState("全部");
  const [maxItems, setMaxItems] = useState(50);

  const {
    profileResults: results,
    profileLoading: loading,
    profileError: error,
    fetchHome,
    clearProfile,
    removeProfileItems,
    downloadSelected,
  } = useParseStore();

  const handleFetch = async () => {
    if (!homeUrl.trim()) return;
    setSelected(new Set());
    await fetchHome(homeUrl.trim(), maxItems);
    // 解析成功后自动清空输入框 (issue-8)
    if (!useParseStore.getState().profileError) {
      setHomeUrl("");
    }
  };

  const toggleSelect = (index: number) => {
    const next = new Set(selected);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setSelected(next);
  };

  const toggleAll = () => {
    if (selected.size === filtered.length) setSelected(new Set());
    else setSelected(new Set(filtered.map((_, i) => i)));
  };

  const filtered = results.filter((r) => {
    if (typeFilter === "全部") return true;
    if (typeFilter === "视频") return r.type === "video" || r.type === "long_video";
    if (typeFilter === "长视频") return r.type === "long_video";
    if (typeFilter === "图文") return r.type === "image_set";
    return true;
  });

  const handleDownload = async () => {
    const items = selected.size === 0 ? [] : filtered.filter((_, i) => selected.has(i));
    if (items.length === 0) return;
    try {
      const enqueued = await downloadSelected(items);
      // 已入队下载的解析项从列表中移除
      if (enqueued.length > 0) {
        removeProfileItems(new Set(enqueued.map((i) => i.index)));
      }
      setSelected(new Set());
    } catch (e) {
      alert(e instanceof Error ? e.message : "下载入队失败");
    }
  };

  const handleDeleteSelected = () => {
    if (selected.size === 0) return;
    const selectedIndices = new Set(
      filtered.filter((_, i) => selected.has(i)).map((item) => item.index),
    );
    removeProfileItems(selectedIndices);
    setSelected(new Set());
  };

  const handleClearAll = () => {
    clearProfile();
    setSelected(new Set());
  };

  return (
    <div className="flex flex-col h-full">
      {/* Input */}
      <div className="p-6 pb-3">
        <div className="flex gap-2">
          <Input
            placeholder="粘贴用户主页链接，例如 https://www.douyin.com/user/xxxxx"
            value={homeUrl}
            onChange={(e) => setHomeUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleFetch()}
          />
          <Button onClick={handleFetch} disabled={!homeUrl.trim() || loading}>
            {loading ? (
              <>
                <Loader2 size={16} className="mr-1 animate-spin" />
                抓取中
              </>
            ) : (
              "开始抓取"
            )}
          </Button>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="mx-6 mb-3 p-3 bg-red-50 border border-red-200 rounded-sm">
          <div className="flex items-center gap-2 text-sm text-error">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Filter bar */}
      {(results.length > 0 || loading) && (
        <div className="px-6 pb-3">
          <div className="flex items-center gap-3 px-4 py-2 bg-bg-gray rounded-sm text-sm">
            <span className="text-text-secondary text-xs">类型:</span>
            {["全部", "视频", "图文", "长视频"].map((f) => (
              <button
                key={f}
                className={`px-2 py-0.5 rounded text-xs transition-colors ${
                  typeFilter === f
                    ? "bg-purple-100 text-purple-600 font-medium"
                    : "text-text-secondary hover:text-text-primary"
                }`}
                onClick={() => setTypeFilter(f)}
              >
                {f}
              </button>
            ))}
            <span className="text-text-secondary text-xs ml-4">数量上限:</span>
            <select
              className="text-sm font-medium text-text-primary bg-transparent border-none outline-none"
              value={maxItems}
              onChange={(e) => setMaxItems(Number(e.target.value))}
            >
              {[20, 30, 50, 100, 200].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      <div className="border-t border-border-light" />

      {/* Results */}
      {results.length > 0 && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-6 py-2 border-b border-border-light">
            <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                className="w-4 h-4 accent-purple-500"
                checked={filtered.length > 0 && selected.size === filtered.length}
                onChange={toggleAll}
              />
              全选
            </label>
            <span className="text-xs text-text-secondary">
              已选 {selected.size} / 共 {filtered.length} 项
            </span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {filtered.map((item, i) => (
              <div
                key={`${item.awemeId || i}`}
                className={`flex items-center gap-3 px-6 py-2 border-b border-border-light hover:bg-bg-hover transition-colors cursor-pointer ${selected.has(i) ? "bg-bg-selected" : ""}`}
                onClick={() => toggleSelect(i)}
              >
                <input
                  type="checkbox"
                  className="w-4 h-4 accent-purple-500 flex-shrink-0"
                  checked={selected.has(i)}
                  onChange={() => toggleSelect(i)}
                />
                <div className="w-12 h-12 rounded-sm bg-bg-hover flex-shrink-0 flex items-center justify-center text-text-disabled text-xs overflow-hidden">
                  {item.coverUrl ? (
                    <img src={item.coverUrl} alt={item.title} className="w-full h-full object-cover" />
                  ) : (
                    "封面"
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-text-primary truncate">{item.title || "未知作品"}</div>
                  <div className="text-xs text-text-secondary mt-0.5">@{item.author || "未知作者"}</div>
                </div>
                <Badge variant={item.type === "video" ? "video" : item.type === "image_set" ? "image_set" : "long_video"} />
                <span className="text-xs text-text-secondary w-14 text-right flex-shrink-0">
                  {item.publishedAt ? formatTime(item.publishedAt) : ""}
                </span>
                <span className="text-xs text-text-secondary w-12 text-right flex-shrink-0">
                  {item.duration || (item.imageCount ? `${item.imageCount}张` : "")}
                </span>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-3 px-6 h-14 border-t border-border-light bg-bg-input">
            <span className="text-xs text-text-secondary flex-1">
              已选择 {selected.size} 个作品
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="text-warning"
              disabled={selected.size === 0}
              onClick={handleDeleteSelected}
            >
              删除选中
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-error"
              onClick={handleClearAll}
            >
              清空结果
            </Button>
            <Button disabled={selected.size === 0} onClick={handleDownload}>
              开始下载 ({selected.size})
            </Button>
          </div>
        </div>
      )}

      {/* Empty / Loading */}
      {results.length === 0 && !error && (
        <div className="flex-1 flex items-center justify-center text-text-disabled">
          {loading ? (
            <div className="text-center">
              <Loader2 size={32} className="mx-auto mb-3 animate-spin" />
              <p className="text-sm">正在抓取主页作品...</p>
            </div>
          ) : (
            <div className="text-center">
              <div className="text-4xl mb-3 opacity-50">👤</div>
              <p className="text-sm">输入用户主页链接并点击"开始抓取"</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}