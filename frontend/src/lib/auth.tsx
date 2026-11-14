import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, clearOutbox, clearTokens, flushOutbox, getAccessToken, getRefreshToken, setTokens } from "./api";
import type { User } from "./api";

type AuthState = {
  user: User | null;
  ready: boolean;
  signIn: (phone: string, password: string) => Promise<User>;
  signUp: (
    name: string,
    phone: string,
    password: string,
    role?: string,
    email?: string,
  ) => Promise<User>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // `ready` prevents a flash of the sign-in screen while a stored session is checked.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function restore() {
      if (!getAccessToken() && !getRefreshToken()) {
        setReady(true);
        return;
      }
      try {
        const me = await api.me();
        if (!cancelled) setUser(me);
      } catch {
        clearTokens();
      } finally {
        if (!cancelled) setReady(true);
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (phone: string, password: string) => {
    const tokens = await api.login(phone, password);
    setTokens(tokens.access_token, tokens.refresh_token);
    setUser(tokens.user);
    void flushOutbox();
    return tokens.user;
  }, []);

  const signUp = useCallback(
    async (name: string, phone: string, password: string, role = "caregiver", email?: string) => {
      // Phone is the login identifier in this system, so it must never be blank
      // or duplicated. The server rejects duplicates; formatting is normalised here.
      const normalised = phone.replace(/[^\d+]/g, "");
      const tokens = await api.register(name.trim(), normalised, password, role, email);
      setTokens(tokens.access_token, tokens.refresh_token);
      setUser(tokens.user);
      void flushOutbox();
      return tokens.user;
    },
    [],
  );

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // A failed logout must still clear the local session.
    }
    clearTokens();
    clearOutbox();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, ready, signIn, signUp, signOut }),
    [user, ready, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
