import { useState, useRef, useEffect } from "react";
import { Loader2, AlertCircle, Upload, Monitor, KeyRound, ChevronDown, ChevronUp, Trash2 } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
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

/** 全局自增 ID：跨批次解析保持唯一，避免选中集以数组位置为 key 导致错位/误删 */
let nextItemId = 0;

/** 从视频流列表中选择最高画质流（按带宽/分辨率降序取第一条） */
function pickHighestQuality<T extends { bandwidth?: number; width?: number; height?: number }>(
  streams: T[] | undefined,
): T | undefined {
  if (!streams || streams.length === 0) return undefined;
  return [...streams].sort((a, b) => {
    const ba = a.bandwidth ?? 0;
    const bb = b.bandwidth ?? 0;
    if (ba !== bb) return bb - ba;
    const ha = a.height ?? 0;
    const hb = b.height ?? 0;
    return hb - ha;
  })[0];
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
  /** 全局唯一 ID（跨批次不重复），用作选中集与列表 key */
  id: number;
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
  /**
   * 用户选择的下载分 P（cid 列表）。
   * null = 尚未选择过（默认全选）；非空数组 = 仅下载勾选的 P；
   * 空数组 = 用户已取消全部勾选（该条目不下载任何 P，与"全选"语义区分）。
   */
  selectedPages: number[] | null;
}

export default function BiliFetchPage() {
  const [links, setLinks] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<BiliParsedItem[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // === B 站 Cookie（配置后可解锁 1080P 画质） ===
  const [cookiePanelOpen, setCookiePanelOpen] = useState(false);
  const [cookieInput, setCookieInput] = useState("");
  const [cookieSaved, setCookieSaved] = useState(false);
  const [cookieValid, setCookieValid] = useState<boolean | null>(null);
  const [cookieNickname, setCookieNickname] = useState<string | null>(null);
  const [cookieBusy, setCookieBusy] = useState(false);

  const { addToast } = useToastStore();

  // 启动时加载已保存的 B 站 Cookie 状态
  useEffect(() => {
    api
      .biliGetCookie()
      .then((info) => {
        setCookieSaved(info.has_cookie);
        setCookieValid(info.last_valid);
        setCookieNickname(info.last_nickname);
      })
      .catch(() => {
        // 后端未初始化等场景静默失败
      });
  }, []);

  const handleCookieSave = async () => {
    const cookie = cookieInput.trim();
    if (!cookie) {
      addToast("请先粘贴 B 站 Cookie", "error");
      return;
    }
    setCookieBusy(true);
    try {
      const res = await api.biliSetCookie(cookie, true);
      setCookieSaved(res.saved);
      setCookieValid(res.test_result ? res.test_result.valid : null);
      setCookieNickname(res.test_result ? res.test_result.nickname : null);
      if (res.test_result) {
        if (res.test_result.valid) {
          addToast(
            "B 站 Cookie 已保存并验证通过" + (res.test_result.nickname ? "（" + res.test_result.nickname + "）" : "") + "，可解锁 1080P",
            "success",
          );
        } else {
          addToast("Cookie 已保存，但验证未通过，请检查是否有效", "warning");
        }
      } else {
        addToast("B 站 Cookie 已保存", "success");
      }
      setCookieInput("");
    } catch (e) {
      addToast("保存失败: " + (e instanceof Error ? e.message : "未知错误"), "error");
    } finally {
      setCookieBusy(false);
    }
  };

  const handleCookieTest = async () => {
    const cookie = cookieInput.trim();
    if (!cookie) {
      addToast("请先粘贴要测试的 B 站 Cookie", "error");
      return;
    }
    setCookieBusy(true);
    try {
      const res = await api.biliCookieTest(cookie);
      setCookieValid(res.valid);
      setCookieNickname(res.nickname);
      if (res.valid) {
        addToast("Cookie 有效（" + (res.nickname || "已登录") + "）", "success");
      } else {
        addToast("Cookie 无效: " + res.message, "warning");
      }
    } catch (e) {
      addToast("测试失败: " + (e instanceof Error ? e.message : "未知错误"), "error");
    } finally {
      setCookieBusy(false);
    }
  };

  const handleCookieClear = async () => {
    setCookieBusy(true);
    try {
      await api.biliClearCookie();
      setCookieSaved(false);
      setCookieValid(null);
      setCookieNickname(null);
      setCookieInput("");
      addToast("B 站 Cookie 已清除，下载将回到 720P", "success");
    } catch (e) {
      addToast("清除失败: " + (e instanceof Error ? e.message : "未知错误"), "error");
    } finally {
      setCookieBusy(false);
    }
  };

  // === 解析 ===

  const handleParse = async () => {
    const urls = extractBiliLinks(links);
    if (urls.length === 0) {
      addToast("未找到有效的 B 站链接", "error");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const raw = await api.biliParseUrls(urls);
      const mapped: BiliParsedItem[] = raw.map((r, i) => ({
        id: nextItemId++,
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
        // 多 P 默认全选；把默认选择显式存为全部 cid，空数组表示用户全部取消选择
        selectedPages: r.pages && r.pages.length > 0 ? r.pages.map((p) => p.cid) : null,
      }));
      setResults((prev) => [...prev, ...mapped]);
      const failedCount = mapped.filter((m) => m.error).length;
      if (failedCount > 0) {
        // 有失败项：保留输入，提示可重试
        addToast(
          failedCount === mapped.length
            ? "全部解析失败，输入内容已保留可重试"
            : `${failedCount} 条解析失败，输入内容已保留可重试`,
          failedCount === mapped.length ? "error" : "warning",
        );
      } else {
        // 全部成功才自动清空输入框 (issue-8)
        setLinks("");
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

  const toggleSelect = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const toggleAll = () => {
    const selectable = results.filter((r) => !r.error).map((r) => r.id);
    if (selectable.length > 0 && selected.size === selectable.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(selectable));
    }
  };

  /** 切换分 P 选择（多 P 视频可只下载部分分 P） */
  const togglePage = (itemId: number, cid: number) => {
    setResults((prev) =>
      prev.map((item) => {
        if (item.id !== itemId) return item;
        // null = 未选择（默认全选）→ 首次点击进入"仅选择部分 P"模式
        // null 仅表示默认全选；首次点击应从全部已选中移除当前分 P
        const current = new Set(item.selectedPages ?? item.pages.map((page) => page.cid));
        if (current.has(cid)) current.delete(cid);
        else current.add(cid);
        return { ...item, selectedPages: [...current] };
      }),
    );
  };

  /** 该分 P 是否应被下载（null=默认全选；否则按勾选集合判断） */
  const isPageSelected = (item: BiliParsedItem, cid: number): boolean => {
    return item.selectedPages === null || item.selectedPages.includes(cid);
  };

  // === 下载 ===

  const handleDownload = async () => {
    if (selected.size === 0) return;
    const items = results.filter((r) => !r.error && selected.has(r.id));
    setDownloading(true);
    // 记录成功入队的条目 ID（至少有一个分 P 成功入队），仅移除这些，保留失败项
    const succeededIds = new Set<number>();
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
        // 确定要下载的分 P：用户勾选优先，未选择时全部分 P（无分 P 时用空列表）
        const pages = item.pages.length > 0 ? item.pages : [{ cid: 0, page: 1, title: "", duration: 0 }];
        const selectedPages = item.selectedPages; // 本地变量以便 TS 类型收窄
        const targetPages =
          selectedPages !== null
            ? pages.filter((p) => selectedPages.includes(p.cid))
            : pages;

        let successfulPages = 0;
        let failedPages = 0;
        for (const page of targetPages) {
          try {
            const playurl = await api.biliPlayurl(item.bvid, page.cid || 0);
            // DASH 格式：选最高画质视频流 + 首个音频流；必须校验音频流存在
            if (playurl.dash && playurl.video_streams.length > 0) {
              const video = pickHighestQuality(playurl.video_streams);
              const audio = pickHighestQuality(playurl.audio_streams);
              if (!video) {
                failedPages += 1;
                addToast(`${item.title} 无可用视频流`, "error");
                continue;
              }
              if (!audio) {
                failedPages += 1;
                addToast(`${item.title} P${page.page} 无音频流，跳过（避免产出无声文件）`, "error");
                continue;
              }
              const pageSuffix = pages.length > 1 ? ` P${page.page}` : "";
              downloadItems.push({
                url: video.url,
                no_watermark_url: video.url,
                audio_url: audio.url,
                bvid: item.bvid,
                cid: page.cid || 0,
                page: page.page || 1,
                title: `${item.title}${pageSuffix}`,
                author: item.author,
                type: "video",
                aweme_id: item.bvid,
                cover_url: item.coverUrl,
              });
              successfulPages += 1;
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
              successfulPages += 1;
            } else {
              failedPages += 1;
              addToast(`${item.title} P${page.page} 无可用播放流`, "error");
            }
          } catch (e) {
            failedPages += 1;
            addToast(`${item.title} P${page.page} 获取播放流失败: ${e instanceof Error ? e.message : e}`, "error");
          }
        }
        // 仅当该条目的所有目标分 P 都成功入队时移除；部分失败项保留以便重试
        if (targetPages.length > 0 && successfulPages === targetPages.length && failedPages === 0) {
          succeededIds.add(item.id);
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
      // 仅移除成功入队的条目，失败项保留供用户重试
      if (succeededIds.size > 0) {
        setResults((prev) => prev.filter((r) => !succeededIds.has(r.id)));
        setSelected((prevSel) => {
          const next = new Set(prevSel);
          for (const id of succeededIds) next.delete(id);
          return next;
        });
      }
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
    const ids = new Set(selected);
    setResults((prev) => prev.filter((r) => !ids.has(r.id)));
    setSelected(new Set());
    addToast(`已删除 ${selected.size} 项`, "success");
  };

  return (
    <div className="flex flex-col h-full">
      {/* Input Area */}
      <div className="p-6 pb-0">
        {/* Cookie Config Bar */}
        <div className="mb-3 p-3 bg-bg-gray/60 border border-border-light rounded-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs">
              <KeyRound size={14} className="text-purple-500" />
              <span className="font-medium text-text-primary">B 站 Cookie</span>
              {cookieSaved ? (
                cookieValid === true ? (
                  <span className="px-1.5 py-0.5 rounded text-[11px] bg-green-50 text-green-700 border border-green-200">
                    已配置（1080P 解锁{cookieNickname ? " · " + cookieNickname : ""}）
                  </span>
                ) : cookieValid === false ? (
                  <span className="px-1.5 py-0.5 rounded text-[11px] bg-red-50 text-red-700 border border-red-200">
                    Cookie 已失效
                  </span>
                ) : (
                  <span className="px-1.5 py-0.5 rounded text-[11px] bg-purple-50 text-purple-700 border border-purple-200">
                    已配置（1080P）
                  </span>
                )
              ) : (
                <span className="px-1.5 py-0.5 rounded text-[11px] bg-gray-100 text-text-secondary">
                  未配置（最高 720P）
                </span>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="text-xs h-6 px-2 text-purple-600 hover:text-purple-700"
              onClick={() => setCookiePanelOpen(!cookiePanelOpen)}
            >
              {cookiePanelOpen ? (
                <>
                  <ChevronUp size={12} className="mr-1" /> 收起
                </>
              ) : (
                <>
                  <ChevronDown size={12} className="mr-1" />
                  {cookieSaved ? "修改 Cookie" : "配置 Cookie 解锁 1080P"}
                </>
              )}
            </Button>
          </div>

          {cookiePanelOpen && (
            <div className="mt-3 pt-3 border-t border-border-light flex flex-col gap-2">
              <div className="flex gap-2">
                <Input
                  type="password"
                  placeholder="粘贴 B 站 Cookie（含 SESSDATA=...）"
                  value={cookieInput}
                  onChange={(e) => setCookieInput(e.target.value)}
                  className="flex-1 text-xs"
                  disabled={cookieBusy}
                />
                <Button
                  size="sm"
                  className="text-xs"
                  onClick={handleCookieSave}
                  disabled={!cookieInput.trim() || cookieBusy}
                >
                  {cookieBusy ? <Loader2 size={12} className="animate-spin mr-1" /> : null}
                  保存并测试
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="text-xs"
                  onClick={handleCookieTest}
                  disabled={!cookieInput.trim() || cookieBusy}
                >
                  测试
                </Button>
                {cookieSaved && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-error hover:text-red-700 px-2"
                    onClick={handleCookieClear}
                    disabled={cookieBusy}
                    title="清除已保存的 Cookie"
                  >
                    <Trash2 size={14} />
                  </Button>
                )}
              </div>
              <p className="text-[11px] text-text-secondary">
                提示：在浏览器登录 B 站，按 F12 → 网络 → 复制任意请求中的 Cookie（需包含 SESSDATA）。配置后可解锁 1080P 画质，大会员账号可解锁更高画质。不配置时默认最高 720P。
              </p>
            </div>
          )}
        </div>

        <div className="flex gap-2">
          <Textarea
            placeholder="在此粘贴 B 站视频链接（BV 号 / av 号），每行一个&#10;例如：https://www.bilibili.com/video/BV1GJ411x7h"
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
            {results.map((item) => (
              <div key={item.id}>
                <div
                  className={`flex items-center gap-3 px-6 py-2 border-b border-border-light hover:bg-bg-hover transition-colors cursor-pointer ${selected.has(item.id) ? "bg-bg-selected" : ""} ${item.error ? "opacity-60" : ""}`}
                  onClick={() => !item.error && toggleSelect(item.id)}
                >
                  <input
                    type="checkbox"
                    className="w-4 h-4 accent-purple-500 flex-shrink-0"
                    checked={selected.has(item.id)}
                    onChange={() => !item.error && toggleSelect(item.id)}
                    disabled={!!item.error}
                  />
                  <span className="w-5 flex-shrink-0" />
                  <div className="w-12 h-12 rounded-sm bg-bg-hover flex-shrink-0 flex items-center justify-center text-text-disabled text-xs overflow-hidden">
                    {item.coverUrl ? (
                      <img src={api.proxyImageUrl(item.coverUrl)} alt={item.title} className="w-full h-full object-cover" />
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
                        const checked = isPageSelected(item, p.cid);
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
                              onChange={() => togglePage(item.id, p.cid)}
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
              <p className="text-xs mt-2 opacity-60">支持 BV / av 号视频，多 P 视频可选择性下载</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
