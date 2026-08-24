use std::sync::Mutex;

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, include_image,
};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_window_state::StateFlags;

/// 持有 sidecar 子进程句柄
///
/// `CommandChild` 内部持有 stdin 管道写端。必须让其存活到应用退出：
/// - 若在 setup 中直接丢弃，stdin 会立即 EOF，sidecar 的退出监听线程
///   会立刻终止后端；
/// - 应用退出时借此句柄 kill 引导进程并关闭管道，后端随 EOF 一并退出，
///   避免 backend-sidecar 进程残留占用 18989 端口。
struct SidecarChild(Mutex<Option<CommandChild>>);

/// 打开侧边栏链接（在默认浏览器中打开）
#[tauri::command]
fn open_link(url: String) -> Result<(), String> {
    open::that(&url).map_err(|e| format!("打开链接失败: {}", e))
}

/// 获取应用版本号
#[tauri::command]
fn get_app_version() -> String {
    "0.3.3".to_string()
}

/// 播放本地 .wav 文件（Windows 原生 PlaySoundW，异步非阻塞播放）
///
/// 适用于在触发系统通知时同步播放自定义提示音。
/// 路径应为绝对路径，wav 格式 PCM / ADPCM 均可。
/// 若文件不存在或格式不支持，静默失败。
#[cfg(windows)]
#[tauri::command]
fn play_wav_sound(path: String) {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    #[link(name = "winmm")]
    extern "system" {
        fn PlaySoundW(pszSound: *const u16, hmod: *mut std::ffi::c_void, fdwSound: u32) -> i32;
    }

    const SND_FILENAME: u32 = 0x00020000;
    const SND_ASYNC: u32 = 0x00000001;
    const SND_NODEFAULT: u32 = 0x00000002;

    let wide: Vec<u16> = OsStr::new(&path)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    unsafe {
        PlaySoundW(
            wide.as_ptr(),
            std::ptr::null_mut(),
            SND_ASYNC | SND_FILENAME | SND_NODEFAULT,
        );
    }
}

#[cfg(not(windows))]
#[tauri::command]
fn play_wav_sound(_path: String) {
    // 非 Windows 平台忽略
}

/// WebSocket 前端诊断日志（写入 AppData/logs/ws_diag.log）
///
/// 前端在 WS 连接生命周期的关键节点调用此命令，将运行环境检测、
/// 连接尝试、成功/失败原因写入可检查的诊断文件。
#[tauri::command]
fn log_ws_diag(app: tauri::AppHandle, msg: String) {
    if let Ok(dir) = app.path().app_data_dir() {
        let log_path = dir.join("ws_diag.log");
        if let Ok(mut file) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
        {
            use std::io::Write;
            let _ = writeln!(file, "{}", msg);
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_websocket::init())
        .plugin(tauri_plugin_window_state::Builder::new()
            .with_state_flags(
                StateFlags::SIZE
                    | StateFlags::POSITION
                    | StateFlags::MAXIMIZED
                    | StateFlags::VISIBLE
                    | StateFlags::FULLSCREEN,
            )
            .build())
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .setup(|app| {
            #[cfg(any(target_os = "windows", target_os = "macos"))]
            window_shadows_v2::set_shadows(app, true);

            let show_item = MenuItem::with_id(app, "show", "显示窗口", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            let icon = include_image!("icons/icon.ico");

            let _tray = TrayIconBuilder::new()
                .icon(icon)
                .menu(&menu)
                .tooltip("撷风拾影")
                .on_menu_event(|app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .build(app)?;

            let sidecar_command = app.shell().sidecar("backend-sidecar")
                .map_err(|e| e.to_string())?;
            let (mut _rx, child) = sidecar_command
                .args(&["--host", "127.0.0.1", "--port", "18989"])
                .spawn()
                .map_err(|e| e.to_string())?;
            app.manage(SidecarChild(Mutex::new(Some(child))));

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_link,
            get_app_version,
            play_wav_sound,
            log_ws_diag,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::ExitRequested { .. }) {
                if let Some(state) = app.try_state::<SidecarChild>() {
                    if let Some(child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}