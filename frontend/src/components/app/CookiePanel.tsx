import { useState, useEffect } from "react";
import { Plus, RefreshCw, Trash2, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { Button } from "../ui/button";
import { StatusDot } from "../ui/status-dot";
import { Textarea } from "../ui/textarea";
import { useToastStore } from "../../store/toastStore";
import * as api from "../../lib/api";

interface CookieDisplay {
  id: number;
  label: string;
  status: "valid" | "invalid" | "untested";
  lastUsed: string;
  lastCheck: string;
  failCount: number;
  testing?: boolean;
}

export default function CookiePanel() {
  const [cookies, setCookies] = useState<CookieDisplay[]>([]);
  const [loading, setLoading] = useState(true);
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newCookieContent, setNewCookieContent] = useState("");
  const [newCookieLabel, setNewCookieLabel] = useState("");
  const [testingAll, setTestingAll] = useState(false);
  const { addToast } = useToastStore();

  const loadCookies = async () => {
    setLoading(true);
    try {
      const raw = await api.fetchCookies();
      setCookies(
        raw.map((c) => ({
          id: c.id ?? 0,
          label: c.label || `Cookie #${c.id}`,
          status: c.status as CookieDisplay["status"],
          lastUsed: c.last_used || "",
          lastCheck: c.last_check || "",
          failCount: c.fail_count,
        })),
      );
    } catch (e) {
      addToast("加载 Cookie 列表失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCookies();
  }, []);

  const handleAdd = async () => {
    if (!newCookieContent.trim()) return;
    try {
      await api.addCookie(newCookieContent.trim(), newCookieLabel.trim() || undefined);
      addToast("Cookie 已添加", "success");
      setNewCookieContent("");
      setNewCookieLabel("");
      setShowAddForm(false);
      await loadCookies();
    } catch (e) {
      addToast(`添加失败: ${e instanceof Error ? e.message : "未知错误"}`, "error");
    }
  };

  const handleTest = async (cookieId: number) => {
    setCookies((prev) =>
      prev.map((c) => (c.id === cookieId ? { ...c, testing: true } : c)),
    );
    try {
      const result = await api.testCookie(cookieId);
      setCookies((prev) =>
        prev.map((c) =>
          c.id === cookieId
            ? {
                ...c,
                status: result.is_valid ? "valid" : "invalid",
                testing: false,
              }
            : c,
        ),
      );
      if (result.is_valid) {
        addToast(`Cookie 测试通过${result.user_nickname ? ` (${result.user_nickname})` : ""}`, "success");
      } else {
        addToast(`Cookie 无效: ${result.error_message}`, "warning");
      }
    } catch (e) {
      addToast("测试失败", "error");
      setCookies((prev) =>
        prev.map((c) => (c.id === cookieId ? { ...c, testing: false } : c)),
      );
    }
  };

  const handleTestAll = async () => {
    setTestingAll(true);
    try {
      // 测试所有非 invalid 的 Cookie，并发执行以缩短等待时间
      const testable = cookies.filter((c) => c.status !== "invalid");
      await Promise.allSettled(testable.map((cookie) => handleTest(cookie.id)));
      addToast("全部测试完成", "success");
    } finally {
      setTestingAll(false);
    }
  };

  const handleDelete = async (cookieId: number) => {
    if (!confirm("确定要删除这个 Cookie 吗？")) return;
    try {
      await api.deleteCookie(cookieId);
      addToast("Cookie 已删除", "success");
      await loadCookies();
    } catch (e) {
      addToast("删除失败", "error");
    }
  };

  const stats = {
    total: cookies.length,
    valid: cookies.filter((c) => c.status === "valid").length,
    invalid: cookies.filter((c) => c.status === "invalid").length,
    untested: cookies.filter((c) => c.status === "untested").length,
  };

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-6 h-12 border-b border-border-light">
        <Button size="sm" onClick={() => setShowAddForm(!showAddForm)}>
          <Plus size={14} className="mr-1" /> 添加 Cookie
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={handleTestAll}
          disabled={testingAll || cookies.length === 0}
        >
          {testingAll ? (
            <Loader2 size={14} className="mr-1 animate-spin" />
          ) : (
            <RefreshCw size={14} className="mr-1" />
          )}
          全部测试
        </Button>
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setTutorialOpen(!tutorialOpen)}
        >
          {tutorialOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          教程
        </Button>
      </div>

      {/* Add Form */}
      {showAddForm && (
        <div className="px-6 py-4 border-b border-border-light bg-bg-gray">
          <div className="flex flex-col gap-3 max-w-3xl">
            <div>
              <label className="text-xs text-text-secondary mb-1 block">Cookie 内容</label>
              <Textarea
                placeholder="粘贴完整的 Cookie 字符串..."
                value={newCookieContent}
                onChange={(e) => setNewCookieContent(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-xs text-text-secondary mb-1 block">标签（可选）</label>
                <input
                  className="w-full h-8 px-3 text-sm border border-border-light rounded-sm focus:outline-none focus:border-purple-500"
                  placeholder="例如: 账号1"
                  value={newCookieLabel}
                  onChange={(e) => setNewCookieLabel(e.target.value)}
                />
              </div>
              <div className="flex items-end gap-2">
                <Button size="sm" onClick={handleAdd} disabled={!newCookieContent.trim()}>
                  添加并测试
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setShowAddForm(false)}>
                  取消
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cookie List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full text-text-disabled">
            <Loader2 size={32} className="animate-spin mb-3" />
            <p className="text-sm">加载中...</p>
          </div>
        ) : cookies.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-text-disabled">
            <div className="text-4xl mb-3">🍪</div>
            <p className="text-base font-medium text-text-primary">还没有配置 Cookie</p>
            <p className="text-sm mt-1">配置 Cookie 后才能下载视频</p>
            <Button className="mt-4" size="sm" onClick={() => setShowAddForm(true)}>
              <Plus size={14} className="mr-1" /> 添加 Cookie
            </Button>
          </div>
        ) : (
          <div>
            <div className="px-6 py-1 text-xs text-text-secondary font-medium border-b border-border-light bg-bg-gray">
              Cookie 列表
            </div>
            {cookies.map((cookie) => (
              <div
                key={cookie.id}
                className="flex items-center gap-4 px-6 h-12 border-b border-border-light hover:bg-bg-hover transition-colors"
              >
                <StatusDot status={cookie.status} />
                <span className="text-sm font-medium text-text-primary w-20 truncate">{cookie.label}</span>
                <span className={`text-xs w-12 ${
                  cookie.status === "valid" ? "text-success" :
                  cookie.status === "invalid" ? "text-error" : "text-warning"
                }`}>
                  {cookie.status === "valid" ? "有效" : cookie.status === "invalid" ? "失效" : "未测试"}
                </span>
                <span className="text-xs text-text-disabled flex-1">
                  最后使用: {cookie.lastUsed ? new Date(cookie.lastUsed).toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }) : "-"}
                </span>
                {cookie.testing ? (
                  <Loader2 size={14} className="animate-spin text-purple-500" />
                ) : (
                  <Button variant="ghost" size="sm" className="text-xs" onClick={() => handleTest(cookie.id)}>
                    测试
                  </Button>
                )}
                <button
                  className="text-text-disabled hover:text-error transition-colors"
                  onClick={() => handleDelete(cookie.id)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tutorial */}
      {tutorialOpen && (
        <div className="border-t border-border-light">
          <div className="px-6 py-4 bg-bg-gray">
            <h3 className="text-sm font-semibold text-text-primary mb-2">Cookie 获取教程</h3>
            <ol className="text-xs text-text-secondary space-y-2 list-decimal list-inside">
              <li>打开抖音官网 douyin.com 并登录你的账号</li>
              <li>按 F12 打开开发者工具，切换到 Network（网络）标签</li>
              <li>刷新页面，点击任意网络请求</li>
              <li>在 Request Headers 中找到 Cookie 字段，右键复制完整值</li>
              <li>回到应用，粘贴并点击"添加并测试"</li>
            </ol>
          </div>
        </div>
      )}

      {/* Bottom Status */}
      <div className="flex items-center gap-4 px-6 h-8 border-t border-border-light text-xs text-text-secondary">
        <span>共 {stats.total} 个 Cookie</span>
        {stats.valid > 0 && <span className="text-success">有效 {stats.valid}</span>}
        {stats.invalid > 0 && <span className="text-error">失效 {stats.invalid}</span>}
        {stats.untested > 0 && <span className="text-warning">未测试 {stats.untested}</span>}
      </div>
    </div>
  );
}