/** 系统通知模块 - 使用 Tauri 原生 Rust Toast 通知 */

import { invoke } from "@tauri-apps/api/core";
import { isPermissionGranted, requestPermission } from "@tauri-apps/plugin-notification";

/** 通知权限状态缓存 */
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
    permissionGranted = false;
    return false;
  }
}

/**
 * 发送 Windows 原生 Toast 通知
 *
 * 底层走 Rust 侧 notify-rust（WinRT Toast API），
 * 打包后通知会填入正确的 AUMID（com.cwt15.video-get-tool），
 * 可存入 Windows 通知中心、支持点击激活。
 *
 * 开发调试模式（tauri dev）下通知会显示为 "PowerShell" 名称，
 * 且不会持久化到通知中心，这是已知限制。
 *
 * @param title - 通知标题
 * @param body - 通知正文
 * @param sound - 可选，通知声音文件路径（仅 .wav 格式，打包后有效）
 * @returns 是否成功发送
 */
export async function sendSystemNotification(
  title: string,
  body: string,
  sound?: string,
): Promise<boolean> {
  const granted = await ensurePermission();
  if (!granted) return false;

  try {
    // 调用 Rust 端 plugin:notification|notify 命令
    // 走原生 WinRT Toast，而非 Web Notification API
    await invoke("plugin:notification|notify", {
      options: {
        title,
        body,
        ...(sound ? { sound } : {}),
      },
    });
    return true;
  } catch (e) {
    console.warn("[notify] 原生通知发送失败:", e);
    return false;
  }
}

/**
 * 发送带 .wav 自定义提示音的系统通知（推荐方式）
 *
 * 同时发送原生 Toast 并播放本地 wav 文件。
 *
 * @param title - 通知标题
 * @param body - 通知正文
 * @param wavPath - 本地 .wav 文件绝对路径（可选）
 * @returns 是否成功
 */
export async function sendSystemNotificationWithSound(
  title: string,
  body: string,
  wavPath?: string,
): Promise<boolean> {
  // 1. 发送原生 Toast（传入 sound 参数让 toast 自带声音）
  const notified = await sendSystemNotification(title, body, wavPath);

  // 2. 额外同步播放 wav（确保自定义提示音在所有场景下可闻）
  if (wavPath) {
    try {
      await invoke("play_wav_sound", { path: wavPath });
    } catch (e) {
      console.warn("[notify] wav 播放失败:", e);
    }
  }

  return notified;
}
