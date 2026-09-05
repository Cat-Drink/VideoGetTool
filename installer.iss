; ==============================================================================
; VideoGetTool Inno Setup 安装脚本
;
; 严格遵循规范文档 8.2 节与附录 E。
; 生成 Windows 安装包：dist/VideoGetTool_Setup_v0.2.0.exe
;
; 编译命令::
;
;     "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer.iss
;
; 前置条件::
;   - PyInstaller 打包完成，dist/VideoGetTool/ 目录存在
;   - Inno Setup 6 已安装（含中文语言包）
;   - assets/icon.ico 存在
;
; 关键设计::
;   - 卸载只清理 {app}（Program Files），不清理 %APPDATA%/VideoGetTool/（用户数据保留）
;   - AppId 固定 GUID，发布后不可更改（影响升级识别）
;   - 仅支持 Windows x64
;
; 协议说明::
;   - v0.3.0 起，本项目协议由 MIT 切换为 Apache License 2.0。
;   - 详见 LICENSE、THIRD-PARTY-NOTICES.md 与
;     docs/compliance/v0.3.0-license-migration.md。
; ==============================================================================

	#define MyAppName "VideoGetTool"
; v0.2.1：ISPP 守卫支持 CI 注入版本号
; 本地编译用默认值 0.2.0；CI 用 ISCC /DMyAppVersion=<tag版本> 覆盖
#ifndef MyAppVersion
  #define MyAppVersion "0.4.1"
#endif
#define MyAppPublisher "VideoGetTool Contributors"
#define MyAppExeName "VideoGetTool.exe"
#define MyAppURL "https://github.com/Cat-Drink/VideoGetTool"

[Setup]
; 应用信息
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}

; AppId 固定 GUID，发布后不可更改（影响升级识别）
AppId={{B8F3A2E1-7C4D-4E9F-A1B6-3D5E8F2C7A90}

; 安装目录与开始菜单
DefaultDirName={autopf}\VideoGetTool
DefaultGroupName={#MyAppName}

; 卸载图标与显示名称
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

; 输出配置
OutputDir=dist
OutputBaseFilename=VideoGetTool_Setup_v{#MyAppVersion}

; 安装向导图标
SetupIconFile=assets\icon.ico

; 压缩
Compression=lzma2
SolidCompression=yes

; 架构：仅 64 位
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64

; 权限：安装到 Program Files 需管理员
PrivilegesRequired=admin

; 现代风格向导
WizardStyle=modern

; 不显示选择程序组对话框（使用默认分组）
DisableProgramGroupPage=yes

[Languages]
; 简体中文（默认）
Name: "english"; MessagesFile: "compiler:Default.isl"
; 英文（备选）
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; 桌面快捷方式（默认不勾选，可选）
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"; Flags: unchecked

[Files]
; 打包目录下所有文件（递归）
Source: "dist\VideoGetTool\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; 开始菜单快捷方式
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
; 开始菜单卸载项
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
; 桌面快捷方式（可选）
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后可选启动应用
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理安装目录（不清理 %APPDATA%/VideoGetTool/，用户数据保留）
Type: filesandordirs; Name: "{app}"
