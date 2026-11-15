import type { PrinterStatus } from './types.ts';

export type StateTone = 'active' | 'paused' | 'done' | 'error' | 'idle' | 'offline';

export type StateKey =
  | 'offline'
  | 'idle'
  | 'preparing'
  | 'printing'
  | 'paused'
  | 'finished'
  | 'failed'
  | 'unknown';

/** Map backend gcode_state strings onto a small set the UI knows how to show. */
export function stateKey(status: Pick<PrinterStatus, 'connected' | 'state'> | null | undefined): StateKey {
  if (!status || !status.connected) return 'offline';
  switch ((status.state ?? '').toUpperCase()) {
    case 'IDLE':
    case '':
      return 'idle';
    case 'PREPARE':
    case 'SLICING':
      return 'preparing';
    case 'RUNNING':
    case 'PRINTING':
      return 'printing';
    case 'PAUSE':
    case 'PAUSED':
      return 'paused';
    case 'FINISH':
    case 'FINISHED':
    case 'COMPLETE':
      return 'finished';
    case 'FAILED':
    case 'ERROR':
    case 'CANCELLED':
      return 'failed';
    default:
      return 'unknown';
  }
}

export function stateTone(key: StateKey): StateTone {
  switch (key) {
    case 'printing':
    case 'preparing':
      return 'active';
    case 'paused':
      return 'paused';
    case 'finished':
      return 'done';
    case 'failed':
      return 'error';
    case 'offline':
      return 'offline';
    default:
      return 'idle';
  }
}

/** A print is in progress (controls for pause/resume/stop make sense). */
export function isJobActive(key: StateKey): boolean {
  return key === 'printing' || key === 'paused' || key === 'preparing';
}

export function clampProgress(progress: number | null | undefined): number {
  if (progress == null || Number.isNaN(progress)) return 0;
  return Math.min(100, Math.max(0, progress));
}

/** remaining_time is reported in minutes. */
export function formatRemaining(minutes: number | null | undefined): string | null {
  if (minutes == null || minutes <= 0 || !Number.isFinite(minutes)) return null;
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  return `${h} h ${String(m).padStart(2, '0')} min`;
}

/** Clock time when the print should finish, e.g. "14:35". */
export function formatEta(minutes: number | null | undefined, now: Date = new Date(), locale?: string): string | null {
  if (minutes == null || minutes <= 0 || !Number.isFinite(minutes)) return null;
  const eta = new Date(now.getTime() + minutes * 60_000);
  return eta.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
}

export function formatTemp(current: unknown, target?: unknown): string | null {
  if (typeof current !== 'number' || Number.isNaN(current)) return null;
  const cur = `${Math.round(current)}°`;
  if (typeof target === 'number' && target > 0) return `${cur} / ${Math.round(target)}°`;
  return cur;
}

export function jobName(status: PrinterStatus | null | undefined): string | null {
  if (!status) return null;
  const name = status.subtask_name || status.current_print || status.gcode_file;
  if (!name) return null;
  return name.replace(/\.(gcode|3mf|bgcode)(\.gcode)?$/i, '');
}
