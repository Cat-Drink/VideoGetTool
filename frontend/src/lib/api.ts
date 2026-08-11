/** API 服务层 - 封装所有后端 REST 调用 */

const API_BASE = "http://127.0.0.1:18989/api";

/** 通用请求包装 */
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ============ 数据类型 ============

export type TaskStatus = "pending" | "downloading" | "paused" | "completed" | "failed";

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
  items?: { url: string; title?: string; author?: string; type?: string; aweme_id?: string; cover_url?: string; image_count?: number; no_watermark_url?: string; image_urls?: string[] }[];
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