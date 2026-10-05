import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";

import { api, ApiError, ensureCsrf } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  setMe: (me: Me | null) => void;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

async function fetchMe(): Promise<Me | null> {
  await ensureCsrf();
  try {
    return await api.get<Me>("/auth/me/");
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return null;
    throw err;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 60_000, retry: 1 });

  const setMe = useCallback((me: Me | null) => client.setQueryData(["me"], me), [client]);
  const refresh = useCallback(async () => {
    await client.invalidateQueries({ queryKey: ["me"] });
  }, [client]);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout/");
    } finally {
      client.clear();
      client.setQueryData(["me"], null);
      await ensureCsrf(true);
    }
  }, [client]);

  useEffect(() => {
    const onUnauth = () => {
      client.setQueryData(["me"], null);
    };
    window.addEventListener("btx:unauthenticated", onUnauth);
    return () => window.removeEventListener("btx:unauthenticated", onUnauth);
  }, [client]);

  const value = useMemo<AuthState>(
    () => ({ me: query.data ?? null, loading: query.isLoading, setMe, refresh, logout }),
    [query.data, query.isLoading, setMe, refresh, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Shorthand for the signed-in, fully set-up user (pages behind the guard). */
export function useMe(): Me {
  const { me } = useAuth();
  if (!me) throw new Error("useMe used without a signed-in user");
  return me;
}
