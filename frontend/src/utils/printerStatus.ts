export type PrinterUiState = 'printing' | 'idle' | 'paused' | 'finished' | 'offline' | 'error';

export interface PrinterStatusLike {
  connected?: boolean | null;
  state?: string | null;
}

/**
 * Classify printer status using the same buckets as the main Printers page.
 * Only the firmware/app canonical RUNNING state is considered actively printing;
 * stale job metadata or legacy display strings such as PRINTING do not imply an
 * active print by themselves.
 */
export function classifyPrinterStatus(status: PrinterStatusLike | undefined, hasKnownHmsErrors = false): PrinterUiState {
  if (!status?.connected) return 'offline';
  if (hasKnownHmsErrors) return 'error';

  switch (status.state) {
    case 'RUNNING':
      return 'printing';
    case 'PAUSE':
      return 'paused';
    case 'FINISH':
    case 'FAILED':
      return 'finished';
    default:
      return 'idle';
  }
}
