import { useLocation, useNavigate } from "react-router-dom";
import { cn } from "../lib/utils";
import { Download, Link, User, Moon, Sun } from "lucide-react";
import { useThemeStore } from "../store/themeStore";

const navItems = [
  { id: "batch-fetch", path: "/batch-fetch", label: "批量抓取", icon: "link" },
  { id: "profile-fetch", path: "/profile-fetch", label: "主页抓取", icon: "user" },
  { id: "download", path: "/download", label: "下载任务", icon: "download" },
];

const iconMap: Record<string, React.ReactNode> = {
  download: <Download size={20} />,
  link: <Link size={20} />,
  user: <User size={20} />,
};

export function NavBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useThemeStore();

  return (
    <nav className="flex flex-col w-[200px] min-w-[200px] h-full bg-bg-gray transition-colors">
      {/* Nav Items */}
      <div className="flex-1 flex flex-col gap-0.5 px-2 pt-2">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <button
              key={item.id}
              onClick={() => navigate(item.path)}
              className={cn(
                "flex items-center gap-3 h-11 px-4 rounded-md text-sm transition-colors",
                isActive
                  ? "bg-bg-selected text-purple-500 font-medium"
                  : "text-text-secondary hover:bg-bg-hover hover:text-text-primary",
              )}
            >
              <span className={cn(isActive ? "text-purple-500" : "text-text-secondary")}>
                {iconMap[item.icon]}
              </span>
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Theme Toggle & Version */}
      <div className="px-3 py-3 space-y-2">
        {/* Theme Toggle */}
        <button
          onClick={toggleTheme}
          className="flex items-center gap-3 w-full h-9 px-3 rounded-md text-sm text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          <span>{theme === "dark" ? "浅色模式" : "深色模式"}</span>
        </button>

        {/* Version */}
        <div className="flex items-center justify-between px-3 text-xs text-text-disabled">
          <span>v0.3.0</span>
        </div>
      </div>
    </nav>
  );
}