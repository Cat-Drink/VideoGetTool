
/** API 服务层 - 封装所有后端 REST 调用 */

const API_BASE = "http://127.0.0.1:18989/api";

/** 把远程封面/预览图地址转为本地代理地址。
 *
 * Tauri 2 打包后 WebView 直接加载远程 http/https 图片会被拦截/混合内容
 * 规则阻止（实测仅做 http→https 归一化无法解决），而前端对本地 sidecar
 * （127.0.0.1:18989）的请求始终可用。因此统一经由后端代理抓取图片，
 * 前端 <img> 指向本地地址即可稳定渲染。
 */
export function proxyImageUrl(url?: string | null): string {
  if (!url) return "";
  return API_BASE + "/covers?url=" + encodeURIComponent(url);
}

/** 通用请求包装 */
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ============ 数据类型 ============

export type TaskStatus = "pending" | "downloading" | "paused" | "processing" | "completed" | "failed";
export type CookieStatus = "valid" | "invalid" | "untested";

export interface TaskResponse {
  id: number;
  source_type: string;
  source_url: string | null;
  status: string;
  total_items: number;
  completed_items: number;
  created_at: string;
  updated_at: string;
  download_dir: string;
}

export interface TaskItemResponse {
  id: number | null;
  task_id: number;
  aweme_id: string | null;
  url: string;
  title: string | null;
  author: string | null;
  type: string;
  status: string;
  downloaded_bytes: number;
  total_bytes: number;
  progress: number;
  cover_url: string | null;
  fail_reason: string | null;
  local_path: string | null;
}

export interface ConfigResponse {
  download_dir: string;
  concurrency: number;
  chunk_size: number;
  metadata_format: string;
  onboarding_done: boolean;
  /** 通知总开关 */
  notification_enabled: boolean;
  /** 音效开关 */
  sound_enabled: boolean;
  /** 音效选择（如 "default"/"ding"/"bell"） */
  sound_choice: string;
  /** 音量，范围 0.0-1.0 */
  sound_volume: number;
  /** 自定义 MP3 音效文件路径 */
  custom_sound_url: string;
}

export interface CookieResponse {
  id: number | null;
  content: string;
  label: string | null;
  status: string;
  last_used: string | null;
  last_check: string | null;
  fail_count: number;
  created_at: string;
}

// ============ 健康检查 ============

export async function checkHealth(): Promise<{ status: string }> {
  return request("/health");
}

export async function checkReady(): Promise<{ status: string }> {
  return request("/ready");
}

// ============ 下载任务 API ============

export async function fetchTasks(): Promise<TaskResponse[]> {
  return request("/download/tasks");
}

export async function fetchTaskItems(taskId: number): Promise<TaskItemResponse[]> {
  return request(`/download/tasks/${taskId}/items`);
}

export async function startDownload(params: {
  source_type?: string;
  source_url?: string | null;
  items?: { url: string; title?: string; author?: string; type?: string; aweme_id?: string; cover_url?: string; image_count?: number; no_watermark_url?: string; image_urls?: string[]; item_video_urls?: string[]; item_types?: string[] }[];
  download_dir?: string;
}): Promise<{ task_id: number; message: string }> {
  return request("/download/start", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function pauseDownload(taskItemId: number): Promise<{ message: string }> {
  return request(`/download/pause/${taskItemId}`, { method: "POST" });
}

export async function resumeDownload(taskItemId: number): Promise<{ message: string }> {
  return request(`/download/resume/${taskItemId}`, { method: "POST" });
}

export async function retryDownload(taskItemId: number): Promise<{ message: string }> {
  return request(`/download/retry/${taskItemId}`, { method: "POST" });
}

export async function retryAllFailed(): Promise<{ message: string; retried_count: number }> {
  return request("/download/retry-all", { method: "POST" });
}

export async function pauseAll(): Promise<{ message: string }> {
  return request("/download/pause-all", { method: "POST" });
}

export async function resumeAll(): Promise<{ message: string }> {
  return request("/download/resume-all", { method: "POST" });
}

export async function deleteTaskItem(itemId: number): Promise<{ message: string }> {
  return request(`/download/tasks/items/${itemId}`, { method: "DELETE" });
}

export async function deleteTask(taskId: number): Promise<{ message: string }> {
  return request(`/download/tasks/${taskId}`, { method: "DELETE" });
}

export async function clearCompleted(): Promise<{ message: string }> {
  return request("/download/clear-completed", { method: "POST" });
}

export async function verifyCompletedFiles(): Promise<{ verified_count: number; missing_count: number; missing_items: { id: number; aweme_id: string | null; title: string | null; local_path: string | null }[] }> {
  return request("/download/verify", { method: "POST" });
}

// ============ 爬虫 API ============

/** 后端 /crawler/parse 与 /crawler/fetch-home 返回的解析结果项 */
export interface ParseResult {
  url: string;
  title?: string;
  author?: string;
  type?: "video" | "image_set" | "long_video" | "user_home";
  aweme_id?: string;
  cover_url?: string;
  duration?: string;
  image_count?: number;
  no_watermark_url?: string;
  image_urls?: string[];
  item_video_urls?: string[];
  item_types?: string[];
  publish_time?: string;
  error?: string;
}

export async function parseUrls(urls: string[]): Promise<ParseResult[]> {
  return request("/crawler/parse", {
    method: "POST",
    body: JSON.stringify({ urls }),
  });
}

export async function fetchHome(
  url: string,
  maxItems: number = 50,
): Promise<{ items: ParseResult[]; has_more: boolean; total: number | null }> {
  return request("/crawler/fetch-home", {
    method: "POST",
    body: JSON.stringify({ url, max_items: maxItems, offset: 0 }),
  });
}

// ============ Cookie API ============

export async function fetchCookies(): Promise<CookieResponse[]> {
  return request("/cookie/list");
}

export async function addCookie(content: string, label?: string): Promise<{ id: number; message: string }> {
  return request("/cookie/add", {
    method: "POST",
    body: JSON.stringify({ content, label }),
  });
}

export async function testCookie(cookieId: number): Promise<{ id: number; is_valid: boolean; error_message: string; user_nickname: string | null }> {
  return request(`/cookie/test/${cookieId}`, { method: "POST" });
}

export async function deleteCookie(cookieId: number): Promise<{ message: string }> {
  return request(`/cookie/${cookieId}`, { method: "DELETE" });
}

// ============ 配置 API ============

export async function fetchConfig(): Promise<ConfigResponse> {
  return request("/config");
}

export async function updateConfig(params: Partial<ConfigResponse>): Promise<{ message: string }> {
  return request("/config", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function resetConfig(): Promise<{ message: string }> {
  return request("/config/reset", { method: "POST" });
}

// ============ B 站（Bilibili）API ============

export interface BiliParseResult {
  url: string;
  bvid?: string;
  aid?: number;
  title?: string;
  author?: string;
  author_mid?: number;
  cover_url?: string;
  duration?: number;
  description?: string;
  pages?: { cid: number; page: number; title: string; duration: number }[];
  view_count?: number;
  danmaku_count?: number;
  publish_time?: number;
  tags?: string[];
  mid?: number;
  error?: string;
}

export interface BiliStreamInfo {
  id: number;
  url: string;
  mime_type: string;
  codecs: string;
  width: number;
  height: number;
  /** 视频流码率（bps），用于选择最高画质 */
  bandwidth: number;
}

export interface BiliPlayUrlResult {
  bvid: string;
  cid: number;
  quality: number;
  quality_name: string;
  dash: boolean;
  video_streams: BiliStreamInfo[];
  audio_streams: BiliStreamInfo[];
  url: string;
  duration: number;
}

export async function biliParseUrls(urls: string[], bilibili_cookie?: string): Promise<BiliParseResult[]> {
  return request("/bilibili/parse", {
    method: "POST",
    body: JSON.stringify({ urls, bilibili_cookie }),
  });
}

export async function biliPlayurl(
  bvid: string,
  cid: number,
  quality: number = 80,
  cookie?: string,
): Promise<BiliPlayUrlResult> {
  return request("/bilibili/playurl", {
    method: "POST",
    body: JSON.stringify({ bvid, cid, quality, cookie }),
  });
}

export async function biliFetchSpace(url: string, mid?: number, max_count: number = 50): Promise<{ items: BiliParseResult[]; has_more: boolean; total?: number }> {
  return request("/bilibili/fetch-space", {
    method: "POST",
    body: JSON.stringify({ url, mid, max_count }),
  });
}

export async function biliCookieTest(cookie: string): Promise<{ valid: boolean; nickname: string | null; message: string }> {
  return request("/bilibili/cookie-test", {
    method: "POST",
    body: JSON.stringify({ cookie }),
  });
}

export interface BiliCookieInfo {
  has_cookie: boolean;
  cookie_prefix: string;
  last_valid: boolean | null;
  last_nickname: string | null;
}

export async function biliGetCookie(): Promise<BiliCookieInfo> {
  return request("/bilibili/cookie");
}

export async function biliSetCookie(cookie: string, test: boolean = true): Promise<{
  saved: boolean;
  message: string;
  test_result: { valid: boolean; nickname: string | null; message: string } | null;
}> {
  return request("/bilibili/cookie", {
    method: "POST",
    body: JSON.stringify({ cookie, test }),
  });
}

export async function biliClearCookie(): Promise<{ message: string }> {
  return request("/bilibili/cookie", { method: "DELETE" });
}