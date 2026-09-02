import { useState, useRef } from "react";
import { Upload, FileText, Loader2, AlertCircle, ChevronRight, ChevronDown } from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import { proxyImageUrl } from "../lib/api";
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
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  /** 图文项内图片勾选：条目位置 index → 选中的图片索引数组 */
  const [imageSelection, setImageSelection] = useState<Map<number, number[]>>(new Map());
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    batchResults: parsed,
    batchLoading: loading,
    batchError: error,
    retryingItems,
    parseUrls,
    retryItems,
    clearBatch,
    removeBatchItems,
    downloadSelected,
  } = useParseStore();

  const { addToast } = useToastStore();
  // 当前所有失败项的索引（渲染用）
  const failedIndices = parsed.map((item, i) => (item.error ? i : -1)).filter((i) => i >= 0);

  const handleParse = async () => {
    const urls = extractLinks(links);
    if (urls.length === 0) return;
    setSelected(new Set());
    await parseUrls(urls);
    const state = useParseStore.getState();
    // 整批 API 异常（batchError 非空）：保留输入，不清空
    if (state.batchError) return;
    // 本次新增的结果是 batchResults 末尾 urls.length 条
    const added = state.batchResults.slice(state.batchResults.length - urls.length);
    const failedCount = added.filter((item) => item.error).length;
    if (failedCount > 0) {
      // 有失败项：保留输入，提示可重试
      addToast(`${failedCount} 条解析失败，输入内容已保留可重试`, "warning");
    } else {
      // 全部成功才自动清空输入框 (issue-8)
      setLinks("");
    }
  };

  /** 重试单个失败项：原位替换该条结果 */
  const handleRetryItem = async (index: number) => {
    try {
      await retryItems([index]);
      const updated = useParseStore.getState().batchResults[index];
      if (updated?.error) {
        addToast(`该链接仍解析失败: ${updated.error}`, "error");
      } else {
        addToast("重试成功", "success");
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : "重试失败", "error");
    }
  };

  /** 一键重试所有失败项 */
  const handleRetryAllFailed = async () => {
    if (failedIndices.length === 0) return;
    await retryItems(failedIndices);
    const state = useParseStore.getState();
    const remaining = failedIndices.filter((idx) => state.batchResults[idx]?.error);
    if (remaining.length === 0) {
      addToast("全部失败项重试成功", "success");
    } else {
      addToast(`${remaining.length} 项仍解析失败，可再次重试`, "warning");
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
    const nextImgSel = new Map(imageSelection);
    if (next.has(index)) {
      next.delete(index);
      nextImgSel.delete(index);
    } else {
      next.add(index);
      const item = parsed[index];
      // 图文默认全选其图片；其他类型无图片选择
      if (item?.type === "image_set" && item.imageUrls?.length) {
        nextImgSel.set(index, item.imageUrls.map((_, imgIdx) => imgIdx));
      }
    }
    setSelected(next);
    setImageSelection(nextImgSel);
  };

  const toggleAll = () => {
    if (!parsed) return;
    if (selected.size === parsed.length) {
      setSelected(new Set());
      setImageSelection(new Map());
    } else {
      const nextImgSel = new Map<number, number[]>();
      parsed.forEach((item, i) => {
        if (item.type === "image_set" && item.imageUrls?.length && !item.error) {
          nextImgSel.set(i, item.imageUrls.map((_, imgIdx) => imgIdx));
        }
      });
      setSelected(new Set(parsed.map((_, i) => i)));
      setImageSelection(nextImgSel);
    }
  };

  /** 切换图文项内单张图片的勾选 */
  const toggleImage = (itemIndex: number, imageIdx: number) => {
    const item = parsed[itemIndex];
    if (!item) return;
    const nextImgSel = new Map(imageSelection);
    const current = new Set(nextImgSel.get(itemIndex) ?? item.imageUrls?.map((_, i) => i) ?? []);
    const nextSelected = new Set(selected);
    if (current.has(imageIdx)) {
      current.delete(imageIdx);
    } else {
      current.add(imageIdx);
    }
    if (current.size === 0) {
      // 没有勾选任何图片则取消选中该条目
      nextImgSel.delete(itemIndex);
      nextSelected.delete(itemIndex);
    } else {
      nextImgSel.set(itemIndex, [...current].sort((a, b) => a - b));
      nextSelected.add(itemIndex);
    }
    setImageSelection(nextImgSel);
    setSelected(nextSelected);
  };

  const toggleExpand = (index: number) => {
    const next = new Set(expanded);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setExpanded(next);
  };

  const handleDownload = async () => {
    const items = selected.size === 0 ? [] : parsed.filter((_, i) => selected.has(i));
    if (items.length === 0) return;
    try {
      // 将按位置记录的图片选择转换为按 ParsedResult.index 记录
      const byItemIndex = new Map<number, number[]>();
      items.forEach((item) => {
        const arr = parsed.findIndex((p) => p === item);
        if (arr >= 0) {
          const sel = imageSelection.get(arr);
          if (sel) byItemIndex.set(item.index, sel);
        }
      });
      const enqueued = await downloadSelected(
        items,
        undefined,
        byItemIndex.size > 0 ? byItemIndex : undefined,
      );
      // 已入队下载的解析项从列表中移除
      if (enqueued.length > 0) {
        removeBatchItems(new Set(enqueued.map((i) => i.index)));
        addToast(`下载任务已创建（${enqueued.length} 项）`, "success");
      }
      // 清空选择
      setSelected(new Set());
      setImageSelection(new Map());
      setExpanded(new Set());
    } catch (e) {
      addToast(e instanceof Error ? e.message : "下载入队失败", "error");
    }
  };

  const handleDeleteSelected = () => {
    if (selected.size === 0) return;
    const selectedIndices = new Set(
      parsed.filter((_, i) => selected.has(i)).map((item) => item.index),
    );
    removeBatchItems(selectedIndices);
    setSelected(new Set());
    setImageSelection(new Map());
    setExpanded(new Set());
    addToast(`已删除 ${selected.size} 项`, "success");
  };

  const handleClearAll = () => {
    clearBatch();
    setSelected(new Set());
    setImageSelection(new Map());
    setExpanded(new Set());
    addToast("已清空所有解析结果", "success");
  };

  return (
    <div className="flex flex-col h-full">
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
            {parsed.map((item, i) => {
              const isImageSet = !item.error && item.type === "image_set";
              const isExpanded = expanded.has(i);
              const imgSelCount = isImageSet
                ? (imageSelection.get(i)?.length ?? item.imageUrls?.length ?? 0)
                : 0;
              const totalImgs = item.imageUrls?.length ?? 0;
              return (
                <div key={item.awemeId || item.url || `item-${item.index}`}>
                  <div
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
                    {isImageSet ? (
                      <button
                        className="flex-shrink-0 text-text-secondary hover:text-text-primary p-0.5 rounded"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleExpand(i);
                        }}
                        title={isExpanded ? "收起图片列表" : "展开图片列表"}
                      >
                        {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                      </button>
                    ) : (
                      <span className="w-5 flex-shrink-0" />
                    )}
                    <div className="w-12 h-12 rounded-sm bg-bg-hover flex-shrink-0 flex items-center justify-center text-text-disabled text-xs overflow-hidden">
                      {item.coverUrl ? (
                        <img src={proxyImageUrl(item.coverUrl)} alt={item.title} className="w-full h-full object-cover" />
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
                    {item.error && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="flex-shrink-0 text-xs"
                        disabled={retryingItems.has(i)}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRetryItem(i);
                        }}
                      >
                        {retryingItems.has(i) ? (
                          <Loader2 size={14} className="mr-1 animate-spin" />
                        ) : null}
                        重试
                      </Button>
                    )}
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
                  {/* 图文条目展开的图片选择区 */}
                  {isImageSet && isExpanded && totalImgs > 0 && (
                    <div className="px-6 py-3 pl-[5.5rem] bg-bg-gray/50 border-b border-border-light">
                      <div className="text-xs text-text-secondary mb-2">
                        已勾选 {imgSelCount} / {totalImgs} 张图片
                      </div>
                      <div className="grid grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-2 max-h-56 overflow-y-auto">
                        {(item.imageUrls || []).map((imgUrl, imgIdx) => {
                          const checked = imageSelection.get(i)?.includes(imgIdx) ?? true;
                          return (
                            <div key={imgIdx} className="relative group">
                              <input
                                type="checkbox"
                                className="absolute top-1 left-1 w-4 h-4 accent-purple-500 z-10"
                                checked={checked}
                                onChange={() => toggleImage(i, imgIdx)}
                                onClick={(e) => e.stopPropagation()}
                              />
                              <img
                                src={proxyImageUrl(imgUrl)}
                                alt={`图片 ${imgIdx + 1}`}
                                className={`w-full aspect-square object-cover rounded-sm border ${checked ? "border-purple-400" : "border-border-light opacity-40"} transition-colors`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleImage(i, imgIdx);
                                }}
                              />
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
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
              className="text-warning"
              disabled={failedIndices.length === 0}
              onClick={handleRetryAllFailed}
              title="重试所有解析失败的链接"
            >
              重试失败项 ({failedIndices.length})
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
