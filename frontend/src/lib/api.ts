import { storage } from "@/src/utils/storage";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;
const TOKEN_KEY = "wp_auth_token";

export async function getToken(): Promise<string | null> {
  return storage.secureGet<string | null>(TOKEN_KEY, null);
}
export async function setToken(token: string) {
  return storage.secureSet(TOKEN_KEY, token);
}
export async function clearToken() {
  return storage.secureRemove(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// Global 401 handler — set by AuthContext so expired tokens log the user out.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

async function request<T = any>(method: string, path: string, body?: any): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  let data: any = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    // Auth expired/invalid: trigger global logout (but not for the login/auth calls themselves).
    if (res.status === 401 && onUnauthorized && !path.startsWith("/api/auth/")) {
      onUnauthorized();
    }
    const detail = (data && (data.detail || data.message)) || `Request failed (${res.status})`;
    throw new ApiError(typeof detail === "string" ? detail : "Request failed", res.status);
  }
  return data as T;
}

export const api = {
  get: <T = any>(p: string) => request<T>("GET", p),
  post: <T = any>(p: string, b?: any) => request<T>("POST", p, b),
  put: <T = any>(p: string, b?: any) => request<T>("PUT", p, b),
  del: <T = any>(p: string) => request<T>("DELETE", p),
};

// ---- Types -----------------------------------------------------------------
export type ServerStatus = {
  online: boolean;
  cpu: number | null;
  ram: number | null;
  disk: number | null;
  load: (number | null)[] | null;
  uptime: string | null;
  updates: number | null;
  error: string | null;
  checked_at: string;
};

export type Server = {
  id: string;
  name: string;
  host: string;
  port: number;
  username: string;
  use_ssl: boolean;
  webmin_url: string;
  alerts_enabled: boolean;
  last_status: ServerStatus | null;
  created_at: string;
};

export type MetricSample = {
  ts: string;
  cpu: number | null;
  ram: number | null;
  disk: number | null;
};

export type Alert = {
  id: string;
  server_id: string;
  server_name: string;
  type: "offline" | "online" | "cpu" | "ram" | "updates";
  message: string;
  severity: "critical" | "warning" | "info";
  created_at: string;
};

export type User = {
  user_id: string;
  email: string;
  name?: string;
  picture?: string;
  cpu_threshold: number;
  ram_threshold: number;
  alerts_enabled: boolean;
  poll_interval_minutes: number;
};
