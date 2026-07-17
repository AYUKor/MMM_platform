import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";
import type { AuthSessionV1 } from "../../shared/api/generated/auth-session-v1";
import {
  getAuthSession,
  loginWithCredentials,
  logoutSession,
} from "../../shared/api/auth-admin-client";
import {
  AUTH_FORBIDDEN_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
} from "../../shared/api/credentialed-fetch";
import type { AppPermission } from "../../app/access";
import { hasAnyPermission, hasPermission } from "../../app/access";

type AuthStatus = "loading" | "anonymous" | "authenticated" | "error";

interface AuthContextValue {
  status: AuthStatus;
  session: AuthSessionV1 | null;
  bootstrapError: unknown;
  notice: string | null;
  refreshSession: () => Promise<AuthSessionV1 | null>;
  login: (email: string, password: string) => Promise<AuthSessionV1>;
  logout: () => Promise<void>;
  can: (permission: AppPermission) => boolean;
  canAny: (permissions: readonly AppPermission[]) => boolean;
  clearNotice: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [session, setSession] = useState<AuthSessionV1 | null>(null);
  const [bootstrapError, setBootstrapError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const unauthorizedCheckRef = useRef<Promise<void> | null>(null);
  const forbiddenCheckRef = useRef<Promise<void> | null>(null);

  const applySession = useCallback((next: AuthSessionV1) => {
    setBootstrapError(null);
    setSession(next);
    setStatus(next.authenticated ? "authenticated" : "anonymous");
  }, []);

  const refreshSession = useCallback(async () => {
    setStatus("loading");
    setBootstrapError(null);
    try {
      const next = await getAuthSession();
      applySession(next);
      return next;
    } catch (error) {
      setSession(null);
      setBootstrapError(error);
      setStatus("error");
      return null;
    }
  }, [applySession]);

  useEffect(() => {
    let active = true;
    void getAuthSession().then((next) => {
      if (active) applySession(next);
    }).catch((error: unknown) => {
      if (!active) return;
      setSession(null);
      setBootstrapError(error);
      setStatus("error");
    });
    return () => { active = false; };
  }, [applySession]);

  useEffect(() => {
    const handleUnauthorized = () => {
      if (unauthorizedCheckRef.current) return;
      setNotice("Сессия завершена. Войдите повторно.");
      unauthorizedCheckRef.current = (async () => {
        try {
          const next = await getAuthSession();
          if (next.authenticated) {
            applySession(next);
            setNotice(null);
            return;
          }
        } catch {
          // The original protected 401 remains authoritative for the UI.
        }
        queryClient.clear();
        setSession(null);
        setBootstrapError(null);
        setStatus("anonymous");
      })().finally(() => {
        unauthorizedCheckRef.current = null;
      });
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [applySession, queryClient]);

  useEffect(() => {
    const handleForbidden = () => {
      if (forbiddenCheckRef.current || !session?.authenticated || !session.user) return;
      const currentUser = session.user;
      forbiddenCheckRef.current = (async () => {
        try {
          const next = await getAuthSession();
          if (!next.authenticated || !next.user) return;
          const previousAccess = JSON.stringify({
            userId: currentUser.user_id,
            roleId: currentUser.role.role_id,
            permissions: [...currentUser.permissions].sort(),
          });
          const nextAccess = JSON.stringify({
            userId: next.user.user_id,
            roleId: next.user.role.role_id,
            permissions: [...next.user.permissions].sort(),
          });
          if (previousAccess !== nextAccess) {
            queryClient.clear();
            applySession(next);
          }
        } catch {
          // A permission-level 403 never destroys an otherwise active session.
        }
      })().finally(() => {
        forbiddenCheckRef.current = null;
      });
    };
    window.addEventListener(AUTH_FORBIDDEN_EVENT, handleForbidden);
    return () => window.removeEventListener(AUTH_FORBIDDEN_EVENT, handleForbidden);
  }, [applySession, queryClient, session]);

  const login = useCallback(async (email: string, password: string) => {
    await loginWithCredentials(email, password);
    const next = await getAuthSession();
    if (!next.authenticated) throw new Error("Authenticated session was not established");
    queryClient.clear();
    applySession(next);
    setNotice(null);
    return next;
  }, [applySession, queryClient]);

  const logout = useCallback(async () => {
    try {
      await logoutSession();
    } catch {
      // An already-expired or unreachable server must not leave runtime auth state behind.
    } finally {
      queryClient.clear();
      setSession(null);
      setBootstrapError(null);
      setNotice(null);
      setStatus("anonymous");
    }
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(() => ({
    status,
    session,
    bootstrapError,
    notice,
    refreshSession,
    login,
    logout,
    can: (permission) => hasPermission(session, permission),
    canAny: (permissions) => hasAnyPermission(session, permissions),
    clearNotice: () => setNotice(null),
  }), [bootstrapError, login, logout, notice, refreshSession, session, status]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
