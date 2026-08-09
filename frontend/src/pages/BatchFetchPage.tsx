import { useState, useRef } from "react";
import { Upload, FileText, Loader2, AlertCircle } from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import { useParseStore, extractLinks } from "../store/parseStore";
import { useToastStore } from "../store/toastStore";
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

export default function BatchFetchPage() {
  const { batchLinks: links, setBatchLinks: setLinks } = useUiInputStore();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    batchResults: parsed,
    batchLoading: loading,
    batchError: error,
    parseUrls,
    clearBatch,
    removeBatchItems,
    downloadSelected,
  } = useParseStore();

  const { addToast } = useToastStore();

  const handleParse = async () => {
    const urls = extractLinks(links);
    if (urls.length === 0) return;
    setSelected(new Set());
    await parseUrls(urls);
    // 解析成功后自动清空输入框 (issue-8)
    if (!useParseStore.getState().batchError) {
      setLinks("");
    }
  };

  const handleFileImport = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    setLinks(links ? `${links}\n${text}` : text);
    e.target.value = "";
  };

  const toggleSelect = (index: number) => {
    const next = new Set(selected);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setSelected(next);
  };

  const toggleAll = () => {
    if (!parsed) return;
    if (selected.size === parsed.length) setSelected(new Set());
    else setSelected(new Set(parsed.map((_, i) => i)));
  };

  const handleDownload = async () => {
    const items = selected.size === 0 ? [] : parsed.filter((_, i) => selected.has(i));
    if (items.length === 0) return;
    try {
      const enqueued = await downloadSelected(items);
      // 已入队下载的解析项从列表中移除
      if (enqueued.length > 0) {
        removeBatchItems(new Set(enqueued.map((i) => i.index)));
        addToast(`下载任务已创建（${enqueued.length} 项）`, "success");
      }
      // 清空选择
      setSelected(new Set());
    } catch (e) {
      addToast(e instanceof Error ? e.message : "下载入队失败", "error");
    }
  };

  const handleDeleteSelected = () => {
    if (selected.size === 0) return;
    removeBatchItems(selected);
    setSelected(new Set());
    addToast(`已删除 ${selected.size} 项`, "success");
  };

  const handleClearAll = () => {
    clearBatch();
    setSelected(new Set());
    addToast("已清空所有解析结果", "success");
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center px-6 h-14 border-b border-border-light">
        <h1 className="text-display font-semibold text-text-primary">批量抓取</h1>
      </div>

      {/* Input Area */}
      <div className="p-6 pb-0">
        <div className="flex gap-2">
          <Textarea
            placeholder="在此粘贴抖音链接，每行一个&#10;支持视频链接、图文链接、用户主页链接"
            value={links}
            onChange={(e) => setLinks(e.target.value)}
            className="flex-1"
          />
          <Button
            variant="secondary"
            className="h-auto flex-col gap-1 px-4"
            onClick={handleFileImport}
          >
            <Upload size={20} />
            <span className="text-xs">导入文件</span>
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.csv"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>
        <div className="flex justify-end mt-3">
          <Button onClick={handleParse} disabled={!links.trim() || loading}>
            {loading ? (
              <>
                <Loader2 size={16} className="mr-1 animate-spin" />
                解析中...
              </>
            ) : (
              "开始解析"
            )}
          </Button>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="mx-6 mt-3 p-3 bg-red-50 border border-red-200 rounded-sm">
          <div className="flex items-center gap-2 text-sm text-error">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Divider */}
      <div className="mt-4 border-t border-border-light" />

      {/* Results */}
      {parsed.length > 0 && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-6 py-2 border-b border-border-light">
            <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                className="w-4 h-4 accent-purple-500"
                checked={selected.size === parsed.length}
                onChange={toggleAll}
              />
              全选
            </label>
            <span className="text-xs text-text-secondary">
              已选 {selected.size} / 共 {parsed.length} 项
            </span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {parsed.map((item, i) => (
              <div
                key={i}
                className={`flex items-center gap-3 px-6 py-2 border-b border-border-light hover:bg-bg-hover transition-colors cursor-pointer ${selected.has(i) ? "bg-bg-selected" : ""} ${item.error ? "opacity-60" : ""}`}
                onClick={() => !item.error && toggleSelect(i)}
              >
                <input
                  type="checkbox"
                  className="w-4 h-4 accent-purple-500 flex-shrink-0"
                  checked={selected.has(i)}
                  onChange={() => !item.error && toggleSelect(i)}
                  disabled={!!item.error}
                />
                <div className="w-12 h-12 rounded-sm bg-bg-hover flex-shrink-0 flex items-center justify-center text-text-disabled text-xs overflow-hidden">
                  {item.coverUrl ? (
                    <img src={item.coverUrl} alt={item.title} className="w-full h-full object-cover" />
                  ) : (
                    "封面"
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-text-primary truncate">
                    {item.title || (item.error ? "解析失败" : "未知作品")}
                  </div>
                  <div className="text-xs text-text-secondary mt-0.5">
                    {item.error ? (
                      <span className="text-error">{item.error}</span>
                    ) : (
                      `@${item.author || "未知作者"}`
                    )}
                  </div>
                </div>
                {!item.error && (
                  <>
                    <Badge variant={item.type === "video" ? "video" : item.type === "image_set" ? "image_set" : "long_video"} />
                    <span className="text-xs text-text-secondary w-14 text-right flex-shrink-0">
                      {item.publishedAt ? formatTime(item.publishedAt) : ""}
                    </span>
                    <span className="text-xs text-text-secondary w-12 text-right flex-shrink-0">
                      {item.duration || (item.imageCount ? `${item.imageCount}张` : "")}
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
          {/* Bottom bar */}
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

      {/* Empty / Loading state */}
      {parsed.length === 0 && !error && (
        <div className="flex-1 flex items-center justify-center text-text-disabled">
          {loading ? (
            <div className="text-center">
              <Loader2 size={32} className="mx-auto mb-3 animate-spin" />
              <p className="text-sm">正在解析链接...</p>
            </div>
          ) : (
            <div className="text-center">
              <FileText size={48} className="mx-auto mb-3 opacity-50" />
              <p className="text-sm">粘贴链接后点击"开始解析"</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}