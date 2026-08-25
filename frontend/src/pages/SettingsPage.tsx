import { useState, useEffect } from "react";
import { FolderOpen, Download, Loader2 } from "lucide-react";
import { Button } from "../components/ui/button";
import { useToastStore } from "../store/toastStore";
import { pickDirectory, openExternal } from "../lib/tauri";
import * as api from "../lib/api";

export default function SettingsPage() {
  const [config, setConfig] = useState<api.ConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [concurrency, setConcurrency] = useState(3);
  const { addToast } = useToastStore();

  const loadConfig = async () => {
    setLoading(true);
    try {
      const cfg = await api.fetchConfig();
      setConfig(cfg);
      setConcurrency(cfg.concurrency);
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

  const handleOpenRepo = () => {
    openExternal("https://github.com/Cat-Drink/VideoGetTool");
  };

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center px-6 h-14 border-b border-border-light">
          <h1 className="text-display font-semibold text-text-primary">设置</h1>
        </div>
        <div className="flex-1 flex items-center justify-center text-text-disabled">
          <Loader2 size={32} className="animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center px-6 h-14 border-b border-border-light">
        <h1 className="text-display font-semibold text-text-primary">设置</h1>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Download Settings */}
        <section>
          <h2 className="text-h3 font-semibold text-text-primary mb-3">下载设置</h2>
          <div className="border border-border-light rounded-lg overflow-hidden">
            <div className="px-5 py-4 space-y-0">
              <div className="flex items-center justify-between h-12">
                <span className="text-sm text-text-primary">下载目录</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-secondary max-w-60 truncate">{config?.download_dir || "未设置"}</span>
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
                    className="w-40 h-2 accent-purple-500 cursor-pointer"
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
            </div>
          </div>
        </section>

        {/* Metadata Settings */}
        <section>
          <h2 className="text-h3 font-semibold text-text-primary mb-3">元数据设置</h2>
          <div className="border border-border-light rounded-lg px-5 py-4">
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
        </section>

        {/* Logs */}
        <section>
          <h2 className="text-h3 font-semibold text-text-primary mb-3">日志与反馈</h2>
          <div className="border border-border-light rounded-lg px-5 py-4">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-sm text-text-primary">日志位置</span>
                <p className="text-xs text-text-disabled mt-0.5">%APPDATA%\VideoGetTool\logs\app.log</p>
              </div>
              <Button variant="secondary" size="sm" disabled>
                <Download size={14} className="mr-1" /> 导出日志
              </Button>
            </div>
          </div>
        </section>

        {/* About */}
        <section>
          <h2 className="text-h3 font-semibold text-text-primary mb-3">关于</h2>
          <div className="border border-border-light rounded-lg px-5 py-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-text-primary">VideoGetTool (VGT)</p>
                <p className="text-xs text-text-secondary mt-0.5">版本: v0.3.0</p>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" disabled>检查更新</Button>
                <Button variant="secondary" size="sm" onClick={handleOpenRepo}>开源仓库</Button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}