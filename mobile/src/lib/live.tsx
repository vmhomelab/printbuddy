import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AppState, Platform } from 'react-native';

import { authHeaders } from './api.ts';
import { applyLiveMessage, parseLiveMessage, reconnectDelay, type StatusMap } from './liveState.ts';
import { useSession, isAuthenticated } from './session.tsx';
import type { PrinterStatus } from './types.ts';
import { wsUrl } from './url.ts';

const PING_INTERVAL_MS = 25_000;

interface LiveContextValue {
  statuses: StatusMap;
  connected: boolean;
  /** Seed or refresh one printer from a REST response. */
  setStatus: (id: number, status: PrinterStatus) => void;
}

const LiveContext = createContext<LiveContextValue | null>(null);

type NativeWebSocketCtor = new (url: string, protocols?: string | string[], options?: { headers?: Record<string, string> }) => WebSocket;

/**
 * Holds one WebSocket to /api/v1/ws while the app is in the foreground and
 * merges `printer_status` pushes into a map keyed by printer id.
 */
export function LiveStatusProvider({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const [statuses, setStatuses] = useState<StatusMap>({});
  const [connected, setConnected] = useState(false);
  const [foreground, setForeground] = useState(AppState.currentState !== 'background');
  const attempt = useRef(0);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => setForeground(state === 'active'));
    return () => sub.remove();
  }, []);

  const active = foreground && isAuthenticated(session);
  const serverUrl = session?.serverUrl;
  const kind = session?.kind;
  const token = session?.token ?? null;

  useEffect(() => {
    if (!active || !serverUrl || !kind) return;

    let socket: WebSocket | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const open = () => {
      const url = wsUrl(serverUrl);
      // React Native's WebSocket accepts headers as a third argument; browsers don't.
      socket =
        Platform.OS === 'web'
          ? new WebSocket(url)
          : new (WebSocket as unknown as NativeWebSocketCtor)(url, undefined, { headers: authHeaders({ kind, token }) });

      socket.onopen = () => {
        attempt.current = 0;
        setConnected(true);
        pingTimer = setInterval(() => socket?.send(JSON.stringify({ type: 'ping' })), PING_INTERVAL_MS);
      };
      socket.onmessage = (event) => {
        const msg = parseLiveMessage(event.data);
        if (msg) setStatuses((prev) => applyLiveMessage(prev, msg));
      };
      socket.onerror = () => {
        // onclose follows and handles the retry
      };
      socket.onclose = () => {
        setConnected(false);
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = null;
        if (closed) return;
        retryTimer = setTimeout(open, reconnectDelay(attempt.current++));
      };
    };

    open();

    return () => {
      closed = true;
      if (pingTimer) clearInterval(pingTimer);
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
      setConnected(false);
    };
  }, [active, serverUrl, kind, token]);

  // Drop cached data when switching servers or signing out.
  useEffect(() => {
    setStatuses({});
  }, [serverUrl]);

  const value = useMemo<LiveContextValue>(
    () => ({
      statuses,
      connected,
      setStatus: (id, status) =>
        setStatuses((prev) => applyLiveMessage(prev, { type: 'printer_status', printer_id: id, data: status })),
    }),
    [statuses, connected],
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveContextValue {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error('useLive must be used inside <LiveStatusProvider>');
  return ctx;
}
