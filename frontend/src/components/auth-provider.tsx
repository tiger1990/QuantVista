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
import type { components } from "@/lib/api/schema";

type TokenEnvelope = components["schemas"]["Envelope_TokenResponse_"];

/** Pull the access token out of a token-response envelope (typed by the generated client). */
function accessTokenFrom(body: TokenEnvelope | undefined): string | null {
  return body?.data?.access_token ?? null;
}

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

// Responses are now fully typed by the generated client (backend endpoints declare
// `response_model=Envelope[XResponse]`), so no manual narrowing is needed.
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  const applyToken = useCallback(async (token: string) => {
    setAccessToken(token);
    const { data } = await api.GET("/api/v1/me");
    const me = data?.data ?? null;
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
