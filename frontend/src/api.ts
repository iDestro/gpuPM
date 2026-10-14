import { translate, getLocale } from "./i18n";
import { QueryClient } from "@tanstack/react-query";
export type Session = { username: string; csrf_token: string };
let session: Session | null = null;
export function setSession(value: Session | null) {
  session = value;
}
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      refetchIntervalInBackground: false,
      staleTime: 5000,
    },
    mutations: { retry: false },
  },
});
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (method !== "GET" && session) headers["X-CSRF-Token"] = session.csrf_token;
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login") {
      setSession(null);
      queryClient.clear();
      window.dispatchEvent(new Event("gpupm:unauthorized"));
    }
    throw new ApiError(
      response.status,
      data?.detail?.code || "http_error",
      data?.detail?.message || data?.detail || `请求失败 (${response.status})`,
    );
  }
  return data as T;
}
export function params(values: Record<string, unknown>) {
  const p = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== null && value !== "")
      p.set(key, String(value));
  return p.size ? `?${p}` : "";
}
export function bytes(value: number | null | undefined) {
  if (value == null) return translate("无数据");
  if (value === 0) return "0 B";
  const unit = Math.min(4, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** unit).toFixed(1)} ${["B", "KiB", "MiB", "GiB", "TiB"][unit]}`;
}
export function date(value: string | null | undefined) {
  return value
    ? new Date(value).toLocaleString(getLocale(), {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "—";
}
export function duration(value: number | null | undefined) {
  if (value == null) return translate("无数据");
  const n = Math.abs(value);
  return `${value < 0 ? translate("超时 ") : ""}${translate("{hours}时 {minutes}分", { hours: Math.floor(n / 3600), minutes: Math.floor((n % 3600) / 60) })}`;
}
