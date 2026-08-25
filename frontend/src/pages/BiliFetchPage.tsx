import { useState, useRef } from "react";
import { Loader2, AlertCircle, Upload, FileText, Monitor } from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import * as api from "../lib/api";
import { useToastStore } from "../store/toastStore";

/** Unix 秒 → 短格式展示（YYYY-MM-DD） */
function formatUnix(ts: number | undefined): string {
  if (!ts) return "";
  try {
    const d = new Date(ts * 1000);
    if (isNaN(d.getTime())) return "";
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  } catch {
    return "";
  }
}

/** 秒 → 时长文本（mm:ss / h:mm:ss） */
function formatDuration(sec: number | undefined): string {
  if (!sec || sec <= 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** 从文本中提取 B 站链接（每行一条） */
function extractBiliLinks(text: string): string[] {
  const lines = text.split(/[\n\r]+/);
  const urls: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    // 提取行内 URL（含 https:// 的片段）
    const match = trimmed.match(/https?:\/\/[^\s，。、！？,;；)）\]]+/i);
    if (match) {
      urls.push(match[0].replace(/[.,;:)]+$/, ""));
    }
  }
  return urls;
}

interface BiliParsedItem {
  index: number;
  url: string;
  bvid?: string;
  title: string;
  author: string;
  coverUrl?: string;
  duration?: number;
  pages: { cid: number; page: number; title: string; duration: number }[];
  viewCount?: number;
  publishTime?: number;
  mid?: number;
  error?: string;
  /** 用户选择的下载分 P（cid 列表），为空表示整条视频全部分 P */
  selectedPages: number[];
}

export default function BiliFetchPage() {
  const [links, setLinks] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<BiliParsedItem[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { addToast } = useToastStore();

  // === 解析 ===

  const handleParse = async () => {
    const urls = extractBiliLinks(links);
    if (urls.length === 0) {
      addToast("未找到有效的 B 站链接", "error");
      return;
    }
    setLoading(true);
    setError(null);
    setSelected(new Set());
    try {
      const raw = await api.biliParseUrls(urls);
      const mapped: BiliParsedItem[] = raw.map((r, i) => ({
        index: i,
        url: urls[i] || r.url || "",
        bvid: r.bvid,
        title: r.title || "",
        author: r.author || "",
        coverUrl: r.cover_url,
        duration: r.duration,
        pages: r.pages || [],
        viewCount: r.view_count,
        publishTime: r.publish_time,
        mid: r.mid,
        error: r.error,
        selectedPages: [],
      }));
      setResults((prev) => [...prev, ...mapped]);
      setLinks("");
      if (mapped.every((m) => m.error)) {
        addToast("全部解析失败，请检查链接或稍后重试", "error");
      } else {
        addToast(`解析完成：${mapped.length} 条`, "success");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "解析失败");
    } finally {
      setLoading(false);
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

  // === 选择 ===

  const toggleSelect = (index: number) => {
    const next = new Set(selected);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setSelected(next);
  };

  const toggleAll = () => {
    const selectable = results.filter((r) => !r.error).map((r) => r.index);
    if (selectable.length > 0 && selected.size === selectable.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(selectable));
    }
  };

  /** 切换分 P 选择（多 P 视频可只下载部分分 P） */
  const togglePage = (itemIndex: number, cid: number) => {
    setResults((prev) =>
      prev.map((item, i) => {
        if (i !== itemIndex) return item;
        const current = new Set(item.selectedPages);
        if (current.has(cid)) current.delete(cid);
        else current.add(cid);
        return { ...item, selectedPages: [...current] };
      }),
    );
  };

  // === 下载 ===

  const handleDownload = async () => {
    if (selected.size === 0) return;
    const items = results.filter((_, i) => selected.has(i));
    setDownloading(true);
    try {
      // 对每个选中项：解析分 P → 获取 playurl → 组装 startDownload items
      const downloadItems: {
        url: string;
        title?: string;
        author?: string;
        type?: string;
        aweme_id?: string;
        bvid?: string;
        cid?: number;
        page?: number;
        audio_url?: string;
        no_watermark_url?: string;
        cover_url?: string;
      }[] = [];

      for (const item of items) {
        if (item.error) continue;
        if (!item.bvid) {
          addToast(`${item.title || item.url} 缺少视频 ID，跳过`, "error");
          continue;
        }
        // 确定要下载的分 P：用户勾选优先，未勾选时全部分 P（无分 P 时用空列表）
        const pages = item.pages.length > 0 ? item.pages : [{ cid: 0, page: 1, title: "", duration: 0 }];
        const targetPages =
          item.selectedPages.length > 0
            ? pages.filter((p) => item.selectedPages.includes(p.cid))
            : pages;

        for (const page of targetPages) {
          try {
            const playurl = await api.biliPlayurl(item.bvid, page.cid || 0);
            // DASH 格式：选最高画质视频流 + 首个音频流
            if (playurl.dash && playurl.video_streams.length > 0) {
              const video = playurl.video_streams[0];
              const audio = playurl.audio_streams[0];
              const pageSuffix = pages.length > 1 ? ` P${page.page}` : "";
              downloadItems.push({
                url: video.url,
                no_watermark_url: video.url,
                audio_url: audio?.url || "",
                bvid: item.bvid,
                cid: page.cid || 0,
                page: page.page || 1,
                title: `${item.title}${pageSuffix}`,
                author: item.author,
                type: "video",
                aweme_id: item.bvid,
                cover_url: item.coverUrl,
              });
            } else if (playurl.url) {
              // 非 DASH：单一 MP4
              const pageSuffix = pages.length > 1 ? ` P${page.page}` : "";
              downloadItems.push({
                url: playurl.url,
                no_watermark_url: playurl.url,
                bvid: item.bvid,
                cid: page.cid || 0,
                page: page.page || 1,
                title: `${item.title}${pageSuffix}`,
                author: item.author,
                type: "video",
                aweme_id: item.bvid,
                cover_url: item.coverUrl,
              });
            } else {
              addToast(`${item.title} 无可用播放流`, "error");
            }
          } catch (e) {
            addToast(`${item.title} 获取播放流失败: ${e instanceof Error ? e.message : e}`, "error");
          }
        }
      }

      if (downloadItems.length === 0) {
        addToast("没有可下载的条目", "error");
        return;
      }

      await api.startDownload({
        source_type: "bilibili",
        source_url: null,
        items: downloadItems,
      });
      addToast(`下载任务已创建（${downloadItems.length} 项）`, "success");
      // 移除已入队项
      const selectedIndices = new Set(items.map((i) => i.index));
      setResults((prev) => prev.filter((_, i) => !selectedIndices.has(i)));
      setSelected(new Set());
    } catch (e) {
      addToast(e instanceof Error ? e.message : "下载入队失败", "error");
    } finally {
      setDownloading(false);
    }
  };

  const handleClearAll = () => {
    setResults([]);
    setSelected(new Set());
    addToast("已清空所有解析结果", "success");
  };

  const handleDeleteSelected = () => {
    if (selected.size === 0) return;
    setResults((prev) => prev.filter((_, i) => !selected.has(i)));
    setSelected(new Set());
    addToast(`已删除 ${selected.size} 项`, "success");
  };

  return (
    <div className="flex flex-col h-full">
      {/* Input Area */}
      <div className="p-6 pb-0">
        <div className="flex gap-2">
          <Textarea
            placeholder="在此粘贴 B 站视频链接（BV 号），每行一个&#10;例如：https://www.bilibili.com/video/BV1GJ411x7h"
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
      {results.length > 0 && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-6 py-2 border-b border-border-light">
            <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                className="w-4 h-4 accent-purple-500"
                checked={selected.size === results.filter((r) => !r.error).length}
                onChange={toggleAll}
              />
              全选
            </label>
            <span className="text-xs text-text-secondary">
              已选 {selected.size} / 共 {results.length} 项
            </span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {results.map((item, i) => (
              <div key={item.bvid || item.url || `item-${item.index}`}>
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
                  <span className="w-5 flex-shrink-0" />
                  <div className="w-12 h-12 rounded-sm bg-bg-hover flex-shrink-0 flex items-center justify-center text-text-disabled text-xs overflow-hidden">
                    {item.coverUrl ? (
                      <img src={item.coverUrl} alt={item.title} className="w-full h-full object-cover" />
                    ) : (
                      "封面"
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-text-primary truncate">
                      {item.title || (item.error ? "解析失败" : "未知视频")}
                    </div>
                    <div className="text-xs text-text-secondary mt-0.5">
                      {item.error ? (
                        <span className="text-error">{item.error}</span>
                      ) : (
                        `UP主: @${item.author || "未知"}${
                          item.viewCount ? ` · 播放 ${item.viewCount}` : ""
                        }`
                      )}
                    </div>
                  </div>
                  {!item.error && (
                    <>
                      <Badge variant="video" />
                      {item.pages.length > 1 && (
                        <span className="text-xs text-purple-500 w-14 text-right flex-shrink-0">
                          共 {item.pages.length} P
                        </span>
                      )}
                      <span className="text-xs text-text-secondary w-14 text-right flex-shrink-0">
                        {formatUnix(item.publishTime)}
                      </span>
                      <span className="text-xs text-text-secondary w-14 text-right flex-shrink-0">
                        {formatDuration(item.duration)}
                      </span>
                    </>
                  )}
                </div>
                {/* 多 P 选择区 */}
                {!item.error && item.pages.length > 1 && (
                  <div className="px-6 py-2 pl-[5.5rem] bg-bg-gray/50 border-b border-border-light">
                    <div className="text-xs text-text-secondary mb-1.5">
                      选择要下载的分 P（默认全选）：
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {item.pages.map((p) => {
                        const checked = item.selectedPages.length === 0 || item.selectedPages.includes(p.cid);
                        return (
                          <label
                            key={p.cid}
                            className={`flex items-center gap-1 px-2 py-1 rounded text-xs border cursor-pointer ${checked ? "border-purple-400 bg-purple-50 text-purple-600" : "border-border-light text-text-secondary"}`}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <input
                              type="checkbox"
                              className="w-3.5 h-3.5 accent-purple-500"
                              checked={checked}
                              onChange={() => togglePage(i, p.cid)}
                            />
                            P{p.page}
                            {p.title ? `: ${p.title.slice(0, 12)}` : ""}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
          {/* Bottom bar */}
          <div className="flex items-center gap-3 px-6 h-14 border-t border-border-light bg-bg-input">
            <span className="text-xs text-text-secondary flex-1">
              已选择 {selected.size} 个视频
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
            <Button variant="ghost" size="sm" className="text-error" onClick={handleClearAll}>
              清空结果
            </Button>
            <Button disabled={selected.size === 0 || downloading} onClick={handleDownload}>
              {downloading ? (
                <>
                  <Loader2 size={16} className="mr-1 animate-spin" />
                  获取播放流...
                </>
              ) : (
                `开始下载 (${selected.size})`
              )}
            </Button>
          </div>
        </div>
      )}

      {/* Empty / Loading state */}
      {results.length === 0 && !error && (
        <div className="flex-1 flex items-center justify-center text-text-disabled">
          {loading ? (
            <div className="text-center">
              <Loader2 size={32} className="mx-auto mb-3 animate-spin" />
              <p className="text-sm">正在解析 B 站链接...</p>
            </div>
          ) : (
            <div className="text-center">
              <Monitor size={48} className="mx-auto mb-3 opacity-50" />
              <p className="text-sm">粘贴 B 站视频链接后点击"开始解析"</p>
              <p className="text-xs mt-2 opacity-60">支持 BV 号视频，多 P 视频可选择性下载</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
