"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, setAccessToken } from "@/lib/api/client";

export interface AuthUser {
  userId: string;
  email: string;
  name: string | null;
  tenantId: string;
  tenantName: string;
}

type Status = "loading" | "authed" | "anon";

interface AuthContextValue {
  user: AuthUser | null;
  status: Status;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => Promise<void>;
}

// The backend routes return the standard envelope; responses are `response_model=None`, so we
// narrow the loosely-typed body here (paths + request bodies stay fully typed by the client).
interface Envelope<T> {
  success: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
}

interface MePayload {
  user_id: string;
  email: string;
  name: string | null;
  tenant_id: string;
  tenant_name: string;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function accessTokenFrom(body: unknown): string | null {
  return (body as Envelope<{ access_token: string }>)?.data?.access_token ?? null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  const applyToken = useCallback(async (token: string) => {
    setAccessToken(token);
    const { data } = await api.GET("/api/v1/me");
    const me = (data as Envelope<MePayload>)?.data ?? null;
    setUser(
      me
        ? {
            userId: me.user_id,
            email: me.email,
            name: me.name,
            tenantId: me.tenant_id,
            tenantName: me.tenant_name,
          }
        : null,
    );
    setStatus(me ? "authed" : "anon");
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const { data, error } = await api.POST("/api/v1/auth/login", { body: { email, password } });
      const token = error ? null : accessTokenFrom(data);
      if (!token) throw new Error("Invalid email or password.");
      await applyToken(token);
    },
    [applyToken],
  );

  const register = useCallback(
    async (email: string, password: string, name?: string) => {
      const { data, error } = await api.POST("/api/v1/auth/register", {
        body: { email, password, name: name ?? null },
      });
      const token = error ? null : accessTokenFrom(data);
      if (!token) throw new Error("Could not create the account.");
      await applyToken(token);
    },
    [applyToken],
  );

  const logout = useCallback(async () => {
    await api.POST("/api/v1/auth/logout");
    setAccessToken(null);
    setUser(null);
    setStatus("anon");
  }, []);

  // Silent refresh on load: the httpOnly cookie mints a fresh access token if a session exists.
  useEffect(() => {
    let active = true;
    void (async () => {
      const { data, error } = await api.POST("/api/v1/auth/refresh");
      const token = error ? null : accessTokenFrom(data);
      if (!active) return;
      if (token) await applyToken(token);
      else setStatus("anon");
    })();
    return () => {
      active = false;
    };
  }, [applyToken]);

  const value = useMemo(
    () => ({ user, status, login, register, logout }),
    [user, status, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
