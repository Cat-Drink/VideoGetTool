import { useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./layouts/AppShell";
import { ToastContainer } from "./components/ui/toast";
import { useThemeStore } from "./store/themeStore";
import { useNotificationService } from "./hooks/useNotificationService";
import DownloadPage from "./pages/DownloadPage";
import BatchFetchPage from "./pages/BatchFetchPage";
import ProfileFetchPage from "./pages/ProfileFetchPage";
import OnboardingPage from "./pages/OnboardingPage";
import BiliFetchPage from "./pages/BiliFetchPage";

function App() {
  const { theme } = useThemeStore();

  // 全局通知服务：独立于页面存在，确保任意页面/失焦时都能收到任务级通知与音效
  useNotificationService();

  // 初始化主题
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <>
      <Routes>
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/download" replace />} />
          <Route path="/download" element={<DownloadPage />} />
          <Route path="/batch-fetch" element={<BatchFetchPage />} />
          <Route path="/profile-fetch" element={<ProfileFetchPage />} />
          <Route path="/bili-fetch" element={<BiliFetchPage />} />
        </Route>
      </Routes>
      <ToastContainer />
    </>
  );
}

export default App;