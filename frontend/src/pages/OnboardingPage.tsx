import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { useNavigate } from "react-router-dom";
import { useToastStore } from "../store/toastStore";
import * as api from "../lib/api";
import { pickDirectory } from "../lib/tauri";

type Step = "welcome" | "directory" | "cookie" | "complete";

export default function OnboardingPage() {
  const [step, setStep] = useState<Step>("welcome");
  const [downloadDir, setDownloadDir] = useState("");
  const [cookieValue, setCookieValue] = useState("");
  const [cookieLabel, setCookieLabel] = useState("账号1");
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const { addToast } = useToastStore();
  const navigate = useNavigate();

  // 加载已有配置
  useEffect(() => {
    const init = async () => {
      try {
        const cfg = await api.fetchConfig();
        setDownloadDir(cfg.download_dir);
      } catch {
        setDownloadDir("D:\\Downloads\\VideoGetTool");
      } finally {
        setInitialLoading(false);
      }
    };
    init();
  }, []);

  const stepIndex = ["welcome", "directory", "cookie", "complete"].indexOf(step);

  const handlePickDirectory = async () => {
    const dir = await pickDirectory();
    if (dir) setDownloadDir(dir);
  };

  const handleSaveDir = async () => {
    setLoading(true);
    try {
      await api.updateConfig({ download_dir: downloadDir });
      setStep("cookie");
    } catch (e) {
      addToast("保存目录失败", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleAddAndTestCookie = async () => {
    if (!cookieValue.trim()) return;
    setLoading(true);
    try {
      const result = await api.addCookie(cookieValue.trim(), cookieLabel.trim() || undefined);
      // 测试刚添加的 Cookie
      try {
        const testResult = await api.testCookie(result.id);
        if (testResult.is_valid) {
          addToast(`Cookie 有效${testResult.user_nickname ? ` (${testResult.user_nickname})` : ""}`, "success");
        } else {
          addToast(`Cookie 无效: ${testResult.error_message}`, "warning");
        }
      } catch {
        addToast("Cookie 已添加但测试失败，稍后可在 Cookie 配置页重试", "warning");
      }
      setStep("complete");
    } catch (e) {
      addToast("添加 Cookie 失败", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleSkip = async () => {
    setLoading(true);
    try {
      await api.updateConfig({ onboarding_done: true });
      setStep("complete");
    } catch {
      // 即使保存失败也允许继续
      setStep("complete");
    } finally {
      setLoading(false);
    }
  };

  const handleComplete = async () => {
    setLoading(true);
    try {
      await api.updateConfig({ onboarding_done: true });
      navigate("/download");
    } catch {
      navigate("/download");
    } finally {
      setLoading(false);
    }
  };

  if (initialLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-bg-base">
        <Loader2 size={32} className="animate-spin text-purple-500" />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-bg-base">
      {/* Step Indicator */}
      <div className="flex items-center gap-2 mb-8">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className={`w-2 h-2 rounded-full transition-colors ${
              i <= stepIndex ? "bg-purple-500" : "bg-border-light"
            }`}
          />
        ))}
      </div>

      {/* Welcome */}
      {step === "welcome" && (
        <div className="text-center">
          <div className="w-24 h-24 rounded-2xl bg-purple-500 flex items-center justify-center text-white text-3xl font-bold mx-auto mb-6">
            V
          </div>
          <h1 className="text-display font-semibold text-text-primary mb-2">欢迎使用 VideoGetTool</h1>
          <p className="text-sm text-text-secondary mb-2">一款让你轻松下载抖音视频的桌面工具</p>
          <p className="text-xs text-text-disabled mb-8">无需命令行，配置 Cookie 后即可一键下载</p>
          <Button onClick={() => setStep("directory")}>开始使用</Button>
        </div>
      )}

      {/* Directory */}
      {step === "directory" && (
        <div className="w-96">
          <h2 className="text-h2 font-semibold text-text-primary mb-2">步骤 1：设置下载目录</h2>
          <p className="text-sm text-text-secondary mb-6">选择视频文件保存的位置，建议使用默认目录。</p>
          <div className="flex gap-2">
            <Input value={downloadDir} onChange={(e) => setDownloadDir(e.target.value)} />
            <Button variant="secondary" onClick={handlePickDirectory}>浏览...</Button>
          </div>
          <p className="text-xs text-info mt-2">默认目录为系统下载文件夹下的 VideoGetTool 子文件夹，可随时在设置中修改。</p>
          <div className="flex justify-between mt-8">
            <Button variant="ghost" disabled>上一步</Button>
            <Button onClick={handleSaveDir} disabled={loading || !downloadDir.trim()}>
              {loading ? <Loader2 size={16} className="animate-spin" /> : "下一步"}
            </Button>
          </div>
        </div>
      )}

      {/* Cookie */}
      {step === "cookie" && (
        <div className="w-96">
          <h2 className="text-h2 font-semibold text-text-primary mb-2">步骤 2：配置 Cookie</h2>
          <p className="text-sm text-text-secondary mb-6">抖音需要登录态才能访问视频数据，请按教程获取 Cookie。</p>

          <div className="bg-bg-gray rounded-sm p-4 mb-4 text-xs text-text-secondary space-y-1">
            <p className="font-medium text-text-primary mb-1">Cookie 获取教程（简版）</p>
            <p>1. 打开抖音官网 douyin.com 并登录</p>
            <p>2. 按 F12 打开开发者工具 → Network 标签</p>
            <p>3. 刷新页面，点任意请求，复制 Request Headers 里的 Cookie 值</p>
            <p className="text-purple-500 mt-1">完整教程见 Cookie 配置页 →</p>
          </div>

          <div className="space-y-3">
            <div>
              <label className="text-xs text-text-secondary mb-1 block">Cookie 内容</label>
              <Textarea
                placeholder="在此粘贴 Cookie 字符串..."
                value={cookieValue}
                onChange={(e) => setCookieValue(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-text-secondary mb-1 block">标签</label>
              <Input value={cookieLabel} onChange={(e) => setCookieLabel(e.target.value)} />
            </div>
          </div>

          <div className="flex justify-between mt-8">
            <Button variant="ghost" onClick={() => setStep("directory")}>上一步</Button>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={handleSkip} disabled={loading}>
                跳过，稍后配置
              </Button>
              <Button onClick={handleAddAndTestCookie} disabled={!cookieValue.trim() || loading}>
                {loading ? <Loader2 size={16} className="animate-spin" /> : "添加并测试"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Complete */}
      {step === "complete" && (
        <div className="text-center">
          <div className="w-16 h-16 rounded-full bg-success flex items-center justify-center text-white text-3xl mx-auto mb-6">
            ✓
          </div>
          <h1 className="text-display font-semibold text-text-primary mb-2">配置完成！</h1>
          <p className="text-sm text-text-secondary mb-8">现在可以开始下载抖音视频了</p>
          <Button onClick={handleComplete} disabled={loading}>
            {loading ? <Loader2 size={16} className="animate-spin" /> : "进入应用"}
          </Button>
        </div>
      )}
    </div>
  );
}