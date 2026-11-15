import type { LiveMessage, PrinterStatus } from './types.ts';

export type StatusMap = Readonly<Record<number, PrinterStatus>>;

export function parseLiveMessage(raw: unknown): LiveMessage | null {
  if (typeof raw !== 'string') return null;
  try {
    const msg: unknown = JSON.parse(raw);
    if (msg && typeof msg === 'object' && typeof (msg as { type?: unknown }).type === 'string') {
      return msg as LiveMessage;
    }
  } catch {
    // ignore malformed frames
  }
  return null;
}

/**
 * Apply one WebSocket message to the status map. Returns the same object when
 * nothing changed so React can skip a re-render.
 */
export function applyLiveMessage(map: StatusMap, msg: LiveMessage): StatusMap {
  if (msg.type !== 'printer_status') return map;
  const { printer_id: id, data } = msg as { printer_id: unknown; data: unknown };
  if (typeof id !== 'number' || !data || typeof data !== 'object') return map;
  return { ...map, [id]: { ...map[id], ...(data as PrinterStatus) } };
}

/** Exponential backoff for reconnects: 1s, 2s, 4s … capped at 30s. */
export function reconnectDelay(attempt: number): number {
  return Math.min(30_000, 1_000 * 2 ** Math.max(0, attempt));
}
