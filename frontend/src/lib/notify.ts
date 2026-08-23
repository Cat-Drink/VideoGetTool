/** 系统通知模块 - 使用 Tauri Notification 插件发送 Windows 系统通知 */

import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";

/** 检查并请求通知权限（Windows 10+ 的 Toast 通知权限） */
let permissionGranted: boolean | null = null;

async function ensurePermission(): Promise<boolean> {
  if (permissionGranted === true) return true;
  if (permissionGranted === false) return false;

  try {
    let granted = await isPermissionGranted();
    if (!granted) {
      const permission = await requestPermission();
      granted = permission === "granted";
    }
    permissionGranted = granted;
    return granted;
  } catch {
    // Tauri API 不可用时（如浏览器开发环境）静默降级
    permissionGranted = false;
    return false;
  }
}

/**
 * 发送 Windows 系统通知
 *
 * @param title - 通知标题
 * @param body - 通知正文
 * @returns 是否成功发送
 */
export async function sendSystemNotification(title: string, body: string): Promise<boolean> {
  const granted = await ensurePermission();
  if (!granted) return false;

  try {
    sendNotification({ title, body });
    return true;
  } catch {
    return false;
  }
}
