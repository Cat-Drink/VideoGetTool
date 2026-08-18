import { cn } from "../../lib/utils";
import type { CookieStatus } from "../../lib/api";

const statusColors: Record<CookieStatus, string> = {
  valid: "bg-success",
  invalid: "bg-error",
  untested: "bg-warning",
};

const statusLabels: Record<CookieStatus, string> = {
  valid: "有效",
  invalid: "失效",
  untested: "未测试",
};

export function StatusDot({ status, className }: { status: CookieStatus; className?: string }) {
  return (
    <span
      className={cn("inline-block h-2 w-2 rounded-full", statusColors[status], className)}
      title={statusLabels[status]}
    />
  );
}

export { statusLabels as cookieStatusLabels };