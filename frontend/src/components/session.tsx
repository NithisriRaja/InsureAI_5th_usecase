"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { api, type Role, type SessionOut, type UserOut } from "@/lib/api";
import { sessionStore } from "@/lib/session-store";

/** No sign-in screen: the app works as one of three roles, Admin by default. The role decides
 * which approvals are allowed. Switch it from the sidebar. */
export const ROLES: Role[] = ["retention", "adviser", "admin"];
export const ROLE_USER: Record<Role, string> = {
  retention: "Retention",
  adviser: "Financial Advisor",
  admin: "Admin",
};
const ROLE_KEY = "ipoc.role";
const HEARTBEAT_MS = 60_000;

function savedRole(): Role {
  try {
    const r = localStorage.getItem(ROLE_KEY) as Role | null;
    return r && ROLES.includes(r) ? r : "admin";
  } catch {
    return "admin";
  }
}

async function signIn(role: Role): Promise<void> {
  const s = await api<SessionOut>("/sessions", { method: "POST", body: { name: ROLE_USER[role], role } });
  try {
    localStorage.setItem(ROLE_KEY, role);
  } catch {
    // storage blocked: the role lasts for this page only
  }
  sessionStore.set(s.session_id);
}

type Ctx = { user: UserOut | null; switchRole: (role: Role) => void };
const SessionCtx = createContext<Ctx>({ user: null, switchRole: () => {} });
export const useSession = () => useContext(SessionCtx);

export function SessionProvider({ children }: { children: ReactNode }) {
  const token = useSyncExternalStore(sessionStore.subscribe, sessionStore.get, sessionStore.getServer);
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const qc = useQueryClient();
  const signing = useRef(false);
  const [attempt, setAttempt] = useState(0);

  const me = useQuery({
    queryKey: ["me", token],
    queryFn: () => api<UserOut>("/sessions/me"),
    enabled: !!token,
    retry: false,
    staleTime: Infinity,
  });

  // Sign in automatically (and again after a backend restart, when the old session is gone).
  useEffect(() => {
    if (!mounted || token || signing.current) return;
    signing.current = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    signIn(savedRole())
      .catch(() => {
        retry = setTimeout(() => setAttempt((n) => n + 1), 5000); // backend down: try again later
      })
      .finally(() => {
        signing.current = false;
      });
    return () => clearTimeout(retry);
  }, [mounted, token, attempt]);

  // An older personal sign-in (a typed name) is replaced by the role-based one.
  const name = me.data?.name;
  useEffect(() => {
    if (name && !Object.values(ROLE_USER).includes(name)) {
      api("/sessions/current", { method: "DELETE" }).catch(() => {});
      signIn(savedRole()).catch(() => {});
    }
  }, [name]);

  // Keep the session alive while the tab is visible.
  useEffect(() => {
    if (!token) return;
    const beat = () => {
      if (document.visibilityState === "visible") api("/sessions/heartbeat", { method: "POST" }).catch(() => {});
    };
    const id = setInterval(beat, HEARTBEAT_MS);
    document.addEventListener("visibilitychange", beat);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", beat);
    };
  }, [token]);

  const switchRole = useCallback(
    (role: Role) => {
      api("/sessions/current", { method: "DELETE" }).catch(() => {});
      signIn(role)
        .then(() => qc.invalidateQueries())
        .catch(() => {});
    },
    [qc],
  );

  return <SessionCtx.Provider value={{ user: me.data ?? null, switchRole }}>{children}</SessionCtx.Provider>;
}
