/**
 * Per-printer printer-card view preferences (#1782).
 *
 * The store is keyed by printer id so the toggle on one card cannot rearrange
 * another, and it has to survive whatever is already sitting in localStorage —
 * a value from an older format, or one another tab mangled — without throwing
 * out of a render.
 *
 * The shared test setup stubs localStorage with bare vi.fn()s that store
 * nothing, so this file backs them with a real in-memory object; a round-trip
 * is the whole point of what's under test here.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  isExternalSpoolHidden,
  setExternalSpoolHidden,
} from '../../utils/printerCardPrefs';

const KEY = 'printerHiddenExternalSpools';

let store: Record<string, string>;

function stored(): unknown {
  return JSON.parse(store[KEY]);
}

describe('printerCardPrefs — external spool visibility', () => {
  beforeEach(() => {
    store = {};
    vi.mocked(localStorage.getItem).mockImplementation((key: string) => store[key] ?? null);
    vi.mocked(localStorage.setItem).mockImplementation((key: string, value: string) => {
      store[key] = String(value);
    });
  });

  afterEach(() => {
    vi.mocked(localStorage.getItem).mockReset();
    vi.mocked(localStorage.setItem).mockReset();
  });

  it('defaults to visible for a printer that was never toggled', () => {
    expect(isExternalSpoolHidden(1)).toBe(false);
  });

  it('round-trips the hidden flag through localStorage', () => {
    setExternalSpoolHidden(7, true);
    expect(isExternalSpoolHidden(7)).toBe(true);
    expect(stored()).toEqual({ '7': true });
  });

  it('keeps each printer independent', () => {
    setExternalSpoolHidden(1, true);
    expect(isExternalSpoolHidden(1)).toBe(true);
    expect(isExternalSpoolHidden(2)).toBe(false);

    // Hiding a second printer must not disturb the first — the writer
    // re-reads before merging rather than overwriting the whole object.
    setExternalSpoolHidden(2, true);
    expect(isExternalSpoolHidden(1)).toBe(true);
    expect(isExternalSpoolHidden(2)).toBe(true);
  });

  it('drops the key when shown again rather than storing false', () => {
    setExternalSpoolHidden(3, true);
    setExternalSpoolHidden(3, false);

    expect(isExternalSpoolHidden(3)).toBe(false);
    // Otherwise the object grows an entry for every printer ever toggled twice.
    expect(stored()).toEqual({});
  });

  it('treats malformed stored values as "nothing hidden"', () => {
    for (const junk of ['not json', 'null', '"a string"', '[1,2,3]', '42']) {
      store[KEY] = junk;
      expect(isExternalSpoolHidden(1)).toBe(false);
    }
  });

  it('recovers from a malformed store on the next write', () => {
    store[KEY] = '[1,2,3]';
    setExternalSpoolHidden(5, true);

    expect(isExternalSpoolHidden(5)).toBe(true);
    expect(stored()).toEqual({ '5': true });
  });

  it('survives localStorage being unavailable', () => {
    vi.mocked(localStorage.getItem).mockImplementation(() => {
      throw new Error('SecurityError: access denied');
    });
    vi.mocked(localStorage.setItem).mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });

    // Private-mode browsers throw on both. Neither may escape into a render.
    expect(() => isExternalSpoolHidden(1)).not.toThrow();
    expect(isExternalSpoolHidden(1)).toBe(false);
    expect(() => setExternalSpoolHidden(1, true)).not.toThrow();
  });
});
