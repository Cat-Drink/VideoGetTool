/** Tauri 系统能力封装 */

import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { revealItemInDir } from "@tauri-apps/plugin-opener";

/** 打开文件所在文件夹（在资源管理器中选中该文件） */
export async function openInFolder(path: string): Promise<void> {
  await revealItemInDir(path);
}

/** 打开外部链接 */
export async function openExternal(url: string): Promise<void> {
  try {
    await invoke("open_link", { url });
  } catch {
    // fallback: 直接打开
    window.open(url, "_blank");
  }
}

/** 获取应用版本号 */
export async function getAppVersion(): Promise<string> {
  try {
    return await invoke<string>("get_app_version");
  } catch {
    return "0.2.8";
  }
}

/** 打开文件选择对话框（选择目录） */
export async function pickDirectory(): Promise<string | null> {
  try {
    const selected = await open({
      directory: true,
      multiple: false,
      title: "选择下载目录",
    });
    return selected as string | null;
  } catch {
    return null;
  }
}

/** 打开文件选择对话框（选择文件） */
export async function pickFile(): Promise<string | null> {
  try {
    const selected = await open({
      multiple: false,
      title: "选择文件",
      filters: [{ name: "文本文件", extensions: ["txt", "csv"] }],
    });
    return selected as string | null;
  } catch {
    return null;
  }
}