# Windows 原生 Toast 通知功能参考文档

## 概述

基于 Tauri 2 的 `tauri-plugin-notification` 插件，在 Windows 上使用 **WinRT Toast API**（通过 `notify-rust` 库）发送系统原生通知。通知可存入 Windows 通知中心，支持点击激活应用窗口，并可附带自定义 .wav 提示音。

---

## 架构

```mermaid
flowchart LR
    A[前端 TS 代码] -->|invoke plugin:notification\|notify| B[Rust notify 命令]
    A -->|invoke play_wav_sound| C[Rust play_wav_sound 命令]
    B -->|notify-rust / WinRT Toast| D[Windows 通知中心]
    C -->|PlaySoundW winmm.dll| E[自定义 .wav 播放]
    D -->|用户点击通知| F[tauri-plugin-single-instance 回调]
    F -->|show + set_focus| G[主窗口激活]
```

---

## 前端 TS 调用示例

### 1. 基础通知（无自定义音效）

```typescript
import { sendSystemNotification } from "../lib/notify";

// 发送原生 Toast 通知
await sendSystemNotification("下载完成", "任务 #1 全部下载成功");
```

### 2. 带自定义 .wav 提示音的通知

```typescript
import { sendSystemNotificationWithSound } from "../lib/notify";

// 同时发送 Toast + 播放本地 wav 文件
await sendSystemNotificationWithSound(
  "下载完成",
  "任务 #1 全部下载成功",
  "C:\\Program Files\\MyApp\\sounds\\notification.wav",  // 仅 .wav 格式
);
```

### 3. 使用音效模块（内置合成音 / MP3 / WAV）

```typescript
import { playNotificationSound, playWavSound } from "../lib/sound";

// 内置合成音
playNotificationSound("completed", { choice: "cheerful", volume: 0.7 });

// 自定义 MP3（通过 HTMLAudioElement）
playNotificationSound("completed", {
  choice: "custom",
  customUrl: "C:\\sounds\\done.mp3",
});

// 自定义 WAV（通过 Rust PlaySoundW，纯原生播放）
playNotificationSound("completed", {
  choice: "custom_wav",
  customWavPath: "C:\\sounds\\done.wav",
});

// 直接播放 wav（不联动通知）
await playWavSound("C:\\sounds\\alert.wav");
```

### 4. 通知开关设置

通知开关已集成到后端配置，前端通过 API 读写：

```typescript
import * as api from "../lib/api";

// 读取配置
const cfg = await api.fetchConfig();
console.log("通知开启:", cfg.notification_enabled);
console.log("音效开启:", cfg.sound_enabled);
console.log("音效选择:", cfg.sound_choice);
console.log("自定义音效路径:", cfg.custom_sound_url);

// 保存配置
await api.updateConfig({
  notification_enabled: true,
  sound_enabled: true,
  sound_choice: "custom_wav",
  sound_volume: 0.5,
  custom_sound_url: "C:\\sounds\\done.wav",
});
```

---

## Tauri 配置文件要点

```json
{
  "identifier": "com.cwt15.video-get-tool",
  "bundle": {
    "windows": {
      "nsis": {
        "installMode": "currentUser"
      }
    }
  }
}
```

- **`identifier`**（AUMID）：必须与打包签名一致，**通知中心依赖此 ID 判断通知归属**。
- 打包为 **NSIS 安装包**（安装到用户目录）后，`notify-rust` 会自动填入 AUMID，通知才能正确关联到应用。
- 如需修改 AUMID，需同时更新 `tauri.conf.json` 中的 `identifier` 和 NSIS/WiX 安装包配置。

---

## 点击通知唤起窗口

通过 `tauri-plugin-single-instance` 实现：

```rust
// lib.rs
.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
    // 用户点击通知时，激活并显示主窗口
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}))
```

**原理**：Windows 通知中心点击 Toast 时，如果应用已关闭则会通过 AUMID 启动新实例，如果已运行则通过 `single-instance` 插件回调激活现有窗口。

---

## 开发调试环境通知的已知问题

| 问题 | 说明 | 解决方式 |
|------|------|----------|
| **通知显示为 "PowerShell"** | `tauri dev` 模式下，notify-rust 检测到运行路径在 `target/debug` 下，跳过设置 AUMID，回退到 Shell 默认值 | 打包安装后通知正常显示应用名称 |
| **通知不进入 Windows 通知中心** | 同上，缺少 AUMID 时通知仅为弹出弹窗，不会持久化到通知中心 | 安装运行后自动解决 |
| **点击通知无法激活窗口** | dev 模式下没有 AUMID，点击通知不会触发 single-instance 回调 | 安装运行后自动解决 |
| **自定义 .wav 不播放** | `PlaySoundW` 要求 wav 文件存在且为 PCM/ADPCM 格式，路径错误或格式不支持时静默失败 | 检查 wav 文件路径与格式 |
| **通知权限弹窗** | 首次发送通知时 Windows 会弹出权限请求，用户需允许 | 应用会调用 `requestPermission()` 自动请求 |
| **Web Notification API 与原生混用** | 旧版 `sendNotification` 走 `window.Notification`（Web API），新版走 `plugin:notification\|notify`（Rust 原生） | 使用新版 `sendSystemNotification` |

---

## Capabilities 配置

```json
{
  "permissions": [
    "notification:default",
    "single-instance:default",
    "core:window:allow-show",
    "core:window:allow-set-focus"
  ]
}
```

---

## 依赖清单

### Cargo.toml

```toml
[dependencies]
tauri = { version = "2", features = ["tray-icon", "image-ico"] }
tauri-plugin-notification = "2"
tauri-plugin-single-instance = "2"

[target.'cfg(windows)'.dependencies]
winapi = { version = "0.3", features = ["mmsystem"] }
```

### package.json

```json
{
  "dependencies": {
    "@tauri-apps/api": "^2",
    "@tauri-apps/plugin-notification": "^2.3.3"
  }
}
```

---

## 实现文件清单

| 文件 | 作用 |
|------|------|
| `frontend/src-tauri/src/lib.rs` | Rust 侧：通知插件注册、single-instance 回调、`play_wav_sound` 命令 |
| `frontend/src-tauri/Cargo.toml` | Rust 依赖声明 |
| `frontend/src-tauri/capabilities/default.json` | 权限声明 |
| `frontend/src/lib/notify.ts` | 前端通知模块：封装 Rust 原生通知调用 |
| `frontend/src/lib/sound.ts` | 音效模块：内置合成音、MP3、WAV 播放 |
| `frontend/src/pages/DownloadPage.tsx` | 下载页：通知与音效触发逻辑 |
| `frontend/src/components/app/SettingsPanel.tsx` | 设置面板：通知开关 UI |
| `frontend/src/lib/api.ts` | API 类型定义：`notification_enabled` 等字段 |
