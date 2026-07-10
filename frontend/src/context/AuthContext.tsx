import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { Platform } from "react-native";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";

import { api, setToken, clearToken, getToken, User } from "@/src/lib/api";

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  loginWithGoogle: () => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthState>({} as AuthState);
export const useAuth = () => useContext(AuthContext);

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

async function registerForPush(userId: string) {
  if (Platform.OS === "web" || !Device.isDevice) return;
  try {
    const { status } = await Notifications.requestPermissionsAsync();
    if (status !== "granted") return;
    const tokenResp = await Notifications.getDevicePushTokenAsync();
    await fetch(`${BACKEND_URL}/api/register-push`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, platform: Platform.OS, device_token: tokenResp.data }),
    });
  } catch {
    // non-blocking
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const finishAuth = useCallback(async (token: string, u: User) => {
    await setToken(token);
    setUser(u);
    registerForPush(u.user_id);
  }, []);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    try {
      const token = await getToken();
      if (token) {
        const me = await api.get<User>("/api/auth/me");
        setUser(me);
        registerForPush(me.user_id);
      }
    } catch {
      await clearToken();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.post<{ token: string; user: User }>("/api/auth/login", { email, password });
    await finishAuth(res.token, res.user);
  }, [finishAuth]);

  const register = useCallback(async (email: string, password: string, name?: string) => {
    const res = await api.post<{ token: string; user: User }>("/api/auth/register", { email, password, name });
    await finishAuth(res.token, res.user);
  }, [finishAuth]);

  const processSessionId = useCallback(async (sessionId: string) => {
    const res = await api.post<{ token: string; user: User }>("/api/auth/google", { session_id: sessionId });
    await finishAuth(res.token, res.user);
  }, [finishAuth]);

  const loginWithGoogle = useCallback(async () => {
    const redirectUrl =
      Platform.OS === "web" ? window.location.origin + "/" : Linking.createURL("");
    const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;

    if (Platform.OS === "web") {
      window.location.href = authUrl;
      return;
    }

    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
    if (result.type !== "success" || !result.url) return;
    const url = result.url;
    const frag = url.includes("#") ? url.split("#")[1] : url.split("?")[1] || "";
    const params = new URLSearchParams(frag);
    const sessionId = params.get("session_id");
    if (sessionId) await processSessionId(sessionId);
  }, [processSessionId]);

  // Web: handle session_id present in URL after redirect
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const hash = window.location.hash?.replace(/^#/, "") || "";
    const search = window.location.search?.replace(/^\?/, "") || "";
    const params = new URLSearchParams(hash || search);
    const sessionId = params.get("session_id");
    if (sessionId) {
      processSessionId(sessionId)
        .then(() => window.history.replaceState(null, "", window.location.pathname))
        .catch(() => {});
    }
  }, [processSessionId]);

  const logout = useCallback(async () => {
    await clearToken();
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.get<User>("/api/auth/me");
      setUser(me);
    } catch {}
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, loginWithGoogle, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}
