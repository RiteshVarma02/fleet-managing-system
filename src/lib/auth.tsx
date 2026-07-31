import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, AUTH_STORAGE_KEY, setAccessToken, setUnauthorizedHandler } from "./api/client";
import type { TokenResponse, User } from "./api/types";

interface StoredSession {
  token: string;
  user: User;
  expiresAt: number;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  ready: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

function readSession(): StoredSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredSession;
    if (!parsed?.token || !parsed?.user) return null;
    if (parsed.expiresAt && parsed.expiresAt < Date.now()) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(null);
  const [ready, setReady] = useState(false);

  // Hydrate from storage on the client only (SSR has no session).
  useEffect(() => {
    const stored = readSession();
    if (stored) setAccessToken(stored.token);
    setSession(stored);
    setReady(true);
  }, []);

  const logout = useCallback(() => {
    setAccessToken(null);
    setSession(null);
    if (typeof window !== "undefined") window.localStorage.removeItem(AUTH_STORAGE_KEY);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const result = await api.raw<TokenResponse>("/auth/login", { username, password });
    const next: StoredSession = {
      token: result.access_token,
      user: result.user,
      expiresAt: Date.now() + result.expires_in * 1000,
    };
    setAccessToken(next.token);
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(next));
    setSession(next);
    return next.user;
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user: session?.user ?? null,
      isAuthenticated: Boolean(session),
      isAdmin: session?.user.role === "admin",
      ready,
      login,
      logout,
    }),
    [session, ready, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

export function homeRouteFor(user: User | null) {
  return user?.role === "admin" ? "/fleet" : "/console";
}
