import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 把 http:// 图片地址归一化为 https://。
 *
 * B 站等平台接口常返回 http:// 封面地址；在 Tauri 打包后的 WebView 中，
 * http 子资源会被当作混合内容拦截导致图片不显示，因此统一升级为 https。
 */
export function toHttpsUrl(url?: string | null): string {
  if (url && url.startsWith("http://")) return "https://" + url.slice("http://".length);
  return url || "";
}