/**
 * Per-printer view preferences for the printer card.
 *
 * These are browser-local, like every other printer-page view preference
 * (`printerCardSize`, `hideDisconnectedPrinters`, `printerCollapsedSections`).
 * They describe how one person wants their own screen to look, not anything
 * about the printer, so they deliberately do not go to the backend.
 *
 * Keyed by printer id rather than held as a single global flag: the toggle
 * lives on the card itself, so hiding the external spool on one printer must
 * not silently rearrange every other card in a fleet.
 */

const HIDDEN_EXTERNAL_SPOOLS_KEY = 'printerHiddenExternalSpools';

function readHiddenExternalSpools(): Record<string, boolean> {
  try {
    const saved = localStorage.getItem(HIDDEN_EXTERNAL_SPOOLS_KEY);
    if (!saved) return {};
    const parsed: unknown = JSON.parse(saved);
    // Anything that isn't a plain object (an older format, or a value another
    // tab mangled) is discarded rather than indexed into.
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return parsed as Record<string, boolean>;
  } catch {
    // Malformed JSON, or localStorage unavailable (private mode / blocked
    // cookies). Showing the external spool is the safe default either way.
    return {};
  }
}

/** Whether this printer's external spool should be left out of the card. */
export function isExternalSpoolHidden(printerId: number): boolean {
  return readHiddenExternalSpools()[String(printerId)] === true;
}

/**
 * Persist the toggle. Re-reads before writing so two cards toggled in the same
 * session can't clobber each other's entry, and drops the key entirely when
 * shown again so the stored object doesn't accumulate `false` for every printer
 * the user ever toggled twice.
 */
export function setExternalSpoolHidden(printerId: number, hidden: boolean): void {
  const next = readHiddenExternalSpools();
  if (hidden) {
    next[String(printerId)] = true;
  } else {
    delete next[String(printerId)];
  }
  try {
    localStorage.setItem(HIDDEN_EXTERNAL_SPOOLS_KEY, JSON.stringify(next));
  } catch {
    // Quota exceeded or private mode — the toggle still applies for this
    // session, it just won't survive a reload.
  }
}
