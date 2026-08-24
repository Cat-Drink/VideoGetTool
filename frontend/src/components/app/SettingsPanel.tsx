import { useState, useEffect } from "react";
import {
  Bell,
  FolderOpen,
  Loader2,
  Cookie,
  ChevronRight,
  User,
  Settings2,
  Database,
  FileText,
  MessageSquare,
  RotateCcw,
  ExternalLink,
  Globe,
} from "lucide-react";
import { Button } from "../ui/button";
import { useToastStore } from "../../store/toastStore";
import { usePanelStore } from "../../store/panelStore";
import { pickDirectory, openExternal, getAppVersion } from "../../lib/tauri";
import * as api from "../../lib/api";
import { cn } from "../../lib/utils";

// ─── 卡片折叠项组件 ───────────────────────────────────────────

interface SectionCardProps {
  icon: React.ReactNode;
  title: string;
  description?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function SectionCard({ icon, title, description, open, onToggle, children }: SectionCardProps) {
  return (
    <div className="bg-bg-base rounded-lg border border-border-light overflow-hidden shadow-card">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 h-14 hover:bg-bg-hover transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-purple-500 shrink-0">{icon}</span>
          <div className="text-left">
            <span className="text-sm font-medium text-text-primary">{title}</span>
            {description && (
              <p className="text-xs text-text-disabled mt-0.5">{description}</p>
            )}
          </div>
        </div>
        <ChevronRight
          size={16}
          className={cn(
            "text-text-disabled transition-transform duration-300 shrink-0",
            open ? "rotate-90" : "",
          )}
        />
      </button>
      {open && <div className="border-t border-border-light">{children}</div>}
    </div>
  );
}

// ─── 设置页面主组件 ───────────────────────────────────────────

export default function SettingsPanel() {
  const [config, setConfig] = useState<api.ConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [concurrency, setConcurrency] = useState(3);
  const [notificationEnabled, setNotificationEnabled] = useState(true);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [soundChoice, setSoundChoice] = useState("default");
  const [soundVolume, setSoundVolume] = useState(0.5);
  const [customSoundUrl, setCustomSoundUrl] = useState("");
  const [savingNotify, setSavingNotify] = useState(false);
  const [appVersion, setAppVersion] = useState("v0.3.0");
  const [openSection, setOpenSection] = useState<string | null>("account");
  const { addToast } = useToastStore();
  const { openPanel } = usePanelStore();

  const toggle = (id: string) =>
    setOpenSection((prev) => (prev === id ? null : id));

  useEffect(() => {
    getAppVersion().then((v) => setAppVersion(`v${v}`)).catch(() => {});
  }, []);

  const loadConfig = async () => {
    setLoading(true);
    try {
      const cfg = await api.fetchConfig();
      setConfig(cfg);
      setConcurrency(cfg.concurrency);
      setNotificationEnabled(cfg.notification_enabled);
      setSoundEnabled(cfg.sound_enabled);
      setSoundChoice(cfg.sound_choice);
      setSoundVolume(cfg.sound_volume);
      setCustomSoundUrl(cfg.custom_sound_url ?? "");
    } catch (e) {
      addToast("加载配置失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  const handleSaveConcurrency = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.updateConfig({ concurrency });
      setConfig({ ...config, concurrency });
      addToast("并发数已更新", "success");
    } catch (e) {
      addToast("保存失败", "error");
    } finally {
      setSaving(false);
    }
  };

  const handlePickDirectory = async () => {
    const dir = await pickDirectory();
    if (dir && config) {
      try {
        await api.updateConfig({ download_dir: dir });
        setConfig({ ...config, download_dir: dir });
        addToast("下载目录已更新", "success");
      } catch {
        addToast("保存目录失败", "error");
      }
    }
  };

  const handleSaveNotification = async () => {
    if (!config) return;
    setSavingNotify(true);
    try {
      await api.updateConfig({
        notification_enabled: notificationEnabled,
        sound_enabled: soundEnabled,
        sound_choice: soundChoice,
        sound_volume: soundVolume,
        custom_sound_url: customSoundUrl,
      });
      setConfig({
        ...config,
        notification_enabled: notificationEnabled,
        sound_enabled: soundEnabled,
        sound_choice: soundChoice,
        sound_volume: soundVolume,
        custom_sound_url: customSoundUrl,
      });
      addToast("通知设置已保存", "success");
    } catch (e) {
      addToast("保存通知设置失败", "error");
    } finally {
      setSavingNotify(false);
    }
  };

  if (loading) {
    return (
      <div className="h-full bg-bg-gray flex items-center justify-center text-text-disabled">
        <Loader2 size={32} className="animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full bg-bg-gray flex flex-col">
      {/* 可滚动内容 */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-[560px] mx-auto space-y-3">
          {/* ── 账号管理 ── */}
          <SectionCard
            icon={<User size={18} />}
            title="账号管理"
            description="管理抖音登录 Cookie"
            open={openSection === "account"}
            onToggle={() => toggle("account")}
          >
            <div className="px-5 py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Cookie size={20} className="text-text-secondary" />
                  <div>
                    <span className="text-sm text-text-primary">Cookie 配置</span>
                    <p className="text-xs text-text-disabled mt-0.5">管理抖音登录 Cookie</p>
                  </div>
                </div>
                <Button variant="secondary" size="sm" onClick={() => openPanel("cookie")}>
                  管理
                </Button>
              </div>
            </div>
          </SectionCard>

          {/* ── 下载设置 ── */}
          <SectionCard
            icon={<Settings2 size={18} />}
            title="下载设置"
            description="下载目录、并发数、分块大小"
            open={openSection === "download"}
            onToggle={() => toggle("download")}
          >
            <div className="px-5 py-4 space-y-0">
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">下载目录</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-secondary max-w-48 truncate">{config?.download_dir || "未设置"}</span>
                  <Button variant="secondary" size="sm" onClick={handlePickDirectory}>
                    <FolderOpen size={14} className="mr-1" /> 浏览...
                  </Button>
                </div>
              </div>
              <div className="border-t border-border-light" />
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">并发下载数</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-text-secondary">1</span>
                  <input
                    type="range"
                    min={1}
                    max={10}
                    value={concurrency}
                    onChange={(e) => setConcurrency(Number(e.target.value))}
                    className="w-36 h-2 accent-purple-500 cursor-pointer"
                  />
                  <span className="text-xs text-text-secondary">10</span>
                  <span className="text-sm font-semibold text-purple-500 w-4 text-center">{concurrency}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleSaveConcurrency}
                    disabled={saving || concurrency === config?.concurrency}
                  >
                    {saving ? <Loader2 size={14} className="animate-spin" /> : "保存"}
                  </Button>
                </div>
              </div>
              <div className="border-t border-border-light" />
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">单文件分块大小</span>
                <span className="text-sm text-text-secondary">
                  {config?.chunk_size ? `${(config.chunk_size / (1024 * 1024)).toFixed(0)} MB` : "1 MB"}
                </span>
              </div>
              <div className="border-t border-border-light" />
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">失败重试次数</span>
                <span className="text-sm text-text-disabled">3 次（固定）</span>
              </div>
              <div className="border-t border-border-light" />
            </div>
          </SectionCard>

          {/* ── 元数据设置 ── */}
          <SectionCard
            icon={<Database size={18} />}
            title="元数据设置"
            description="保存格式与附带信息"
            open={openSection === "metadata"}
            onToggle={() => toggle("metadata")}
          >
            <div className="px-5 py-4">
              <div className="flex items-center gap-6">
                <span className="text-sm text-text-primary">元数据保存格式</span>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    className="w-4 h-4 accent-purple-500"
                    checked={config?.metadata_format === "json"}
                    readOnly
                  />
                  JSON
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" className="w-4 h-4 accent-purple-500" disabled />
                  CSV
                </label>
              </div>
            </div>
          </SectionCard>

          {/* ── 日志与反馈 ── */}
          <SectionCard
            icon={<FileText size={18} />}
            title="日志与反馈"
            description="应用日志与问题反馈"
            open={openSection === "logs"}
            onToggle={() => toggle("logs")}
          >
            <div className="px-5 py-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm text-text-primary">日志位置</span>
                  <p className="text-xs text-text-disabled mt-0.5">%APPDATA%\XieFengShiYing\logs\app.log</p>
                </div>
                <Button variant="secondary" size="sm" disabled>
                  <FolderOpen size={14} className="mr-1" /> 导出日志
                </Button>
              </div>
            </div>
          </SectionCard>

          {/* ── 通知设置 ── */}
          <SectionCard
            icon={<Bell size={18} />}
            title="通知设置"
            description="任务完成弹窗与音效"
            open={openSection === "notification"}
            onToggle={() => toggle("notification")}
          >
            <div className="px-5 py-4 space-y-0">
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">任务完成弹窗通知</span>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    className="w-4 h-4 accent-purple-500"
                    checked={notificationEnabled}
                    onChange={(e) => setNotificationEnabled(e.target.checked)}
                  />
                  <span className="text-xs text-text-secondary">{notificationEnabled ? "开启" : "关闭"}</span>
                </label>
              </div>
              <div className="border-t border-border-light" />
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">任务完成音效</span>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    className="w-4 h-4 accent-purple-500"
                    checked={soundEnabled}
                    onChange={(e) => setSoundEnabled(e.target.checked)}
                  />
                  <span className="text-xs text-text-secondary">{soundEnabled ? "开启" : "关闭"}</span>
                </label>
              </div>
              <div className="border-t border-border-light" />
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">音效选择</span>
                <select
                  className="text-sm text-text-secondary bg-bg-base border border-border-light rounded px-2 py-1"
                  value={soundChoice}
                  onChange={(e) => setSoundChoice(e.target.value)}
                >
                  <option value="default">默认音效</option>
                  <option value="soft">轻柔</option>
                  <option value="cheerful">活泼</option>
                  <option value="custom">自定义 MP3</option>
                  <option value="custom_wav">自定义 WAV（原生）</option>
                </select>
              </div>
              {(soundChoice === "custom" || soundChoice === "custom_wav") && (
                <div className="border-t border-border-light" />
              )}
              {(soundChoice === "custom" || soundChoice === "custom_wav") && (
                <div className="flex items-center justify-between h-12">
                  <span className="text-sm text-text-primary">自定义音效文件</span>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      className="text-sm w-48 bg-bg-base border border-border-light rounded px-2 py-1"
                      placeholder={soundChoice === "custom_wav" ? "选择 WAV 文件..." : "选择 MP3 文件..."}
                      value={customSoundUrl}
                      onChange={(e) => setCustomSoundUrl(e.target.value)}
                      readOnly
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        const isWav = soundChoice === "custom_wav";
                        try {
                          const { open } = await import("@tauri-apps/plugin-dialog");
                          const selected = await open({
                            filters: isWav
                              ? [{ name: "WAV 音效", extensions: ["wav"] }]
                              : [{ name: "MP3 音效", extensions: ["mp3"] }],
                            multiple: false,
                          });
                          if (selected) {
                            setCustomSoundUrl(selected);
                          }
                        } catch (e) {
                          // 非 Tauri 环境或对话框失败
                          const path = window.prompt(isWav ? "请输入 WAV 文件路径：" : "请输入 MP3 文件路径：");
                          if (path) setCustomSoundUrl(path);
                        }
                      }}
                    >
                      选择文件
                    </Button>
                  </div>
                </div>
              )}
              <div className="border-t border-border-light" />
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">音效音量</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-text-secondary">0</span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={Math.round(soundVolume * 100)}
                    onChange={(e) => setSoundVolume(Number(e.target.value) / 100)}
                    className="w-36 h-2 accent-purple-500 cursor-pointer"
                  />
                  <span className="text-xs text-text-secondary">100</span>
                  <span className="text-sm font-semibold text-purple-500 w-8 text-center">{Math.round(soundVolume * 100)}%</span>
                </div>
              </div>
              <div className="border-t border-border-light" />
              <div className="flex items-center justify-end h-12">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleSaveNotification}
                  disabled={savingNotify}
                >
                  {savingNotify ? <Loader2 size={14} className="animate-spin" /> : "保存"}
                </Button>
              </div>
            </div>
          </SectionCard>

          {/* ── 底部操作按钮 ── */}
          <div className="flex items-center justify-center gap-3 pt-4 pb-2">
            <button
              onClick={() => openExternal("https://github.com/Cat-Drink/Douyin_Catcher/issues")}
              className="flex items-center gap-2 px-4 h-9 text-sm text-text-secondary bg-bg-base border border-border-light rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors"
            >
              <MessageSquare size={14} />
              问题反馈
            </button>
            <button
              onClick={async () => {
                if (confirm("确定要恢复初始设置吗？此操作不可撤销。")) {
                  try {
                    await api.resetConfig();
                    addToast("配置已重置", "success");
                    await loadConfig();
                  } catch {
                    addToast("重置配置失败", "error");
                  }
                }
              }}
              className="flex items-center gap-2 px-4 h-9 text-sm text-text-secondary bg-bg-base border border-border-light rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors"
            >
              <RotateCcw size={14} />
              恢复初始设置
            </button>
          </div>

          {/* ── 底部关于信息 ── */}
          <div className="text-center pt-4 pb-6 space-y-2">
            <div className="flex items-center justify-center gap-2">
              <span className="text-sm text-text-secondary">撷风拾影 {appVersion}</span>
              <button
                onClick={() => openExternal("https://github.com/Cat-Drink/Douyin_Catcher/releases")}
                className="text-xs text-purple-500 hover:underline"
              >
                检查更新
              </button>
            </div>
            <p className="text-xs text-text-disabled">让复制与粘贴，保持有序</p>
            <div className="flex items-center justify-center gap-4 pt-1">
              <button
                onClick={() => openExternal("https://github.com/Cat-Drink/Douyin_Catcher")}
                className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
              >
                <ExternalLink size={14} />
                GitHub
              </button>
              <button
                onClick={() => openExternal("https://github.com/Cat-Drink/Douyin_Catcher")}
                className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
              >
                <Globe size={14} />
                官方网站
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}