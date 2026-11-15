import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { PrintbuddyApi } from './api.ts';
import { loadSession, saveSession } from './storage.ts';
import type { Session } from './types.ts';

interface SessionContextValue {
  /** false until the stored session has been read from secure storage */
  ready: boolean;
  session: Session | null;
  api: PrintbuddyApi | null;
  /** set when the server rejected our token, so the connect screen can explain why */
  expired: boolean;
  signIn: (session: Session) => Promise<void>;
  signOut: () => Promise<void>;
  /** call when any request returns 401 */
  markExpired: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadSession()
      .then((stored) => {
        if (!cancelled) setSession(stored);
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (next: Session) => {
    await saveSession(next);
    setExpired(false);
    setSession(next);
  }, []);

  const signOut = useCallback(async () => {
    const current = session;
    if (current?.kind === 'jwt') {
      // Best effort: tell the server, but never block sign-out on it.
      new PrintbuddyApi(current, { timeoutMs: 3_000 }).logout().catch(() => undefined);
    }
    await saveSession(null);
    setSession(null);
  }, [session]);

  const markExpired = useCallback(() => {
    setExpired(true);
    // Keep the server URL so the user only has to re-enter credentials.
    setSession((current) => {
      if (!current) return current;
      const next: Session = { serverUrl: current.serverUrl, kind: current.kind, token: null, username: current.username };
      saveSession(next).catch(() => undefined);
      return next;
    });
  }, []);

  const api = useMemo(() => (session && isAuthenticated(session) ? new PrintbuddyApi(session) : null), [session]);

  const value = useMemo<SessionContextValue>(
    () => ({ ready, session, api, expired, signIn, signOut, markExpired }),
    [ready, session, api, expired, signIn, signOut, markExpired],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function isAuthenticated(session: Session | null): boolean {
  if (!session) return false;
  return session.kind === 'none' || Boolean(session.token);
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside <SessionProvider>');
  return ctx;
}

/** For screens behind the auth gate: api is guaranteed to exist there. */
export function useApi(): PrintbuddyApi {
  const { api } = useSession();
  if (!api) throw new Error('useApi called without an authenticated session');
  return api;
}
