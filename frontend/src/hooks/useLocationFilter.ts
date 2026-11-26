import { useCallback, useEffect, useState } from 'react';

/**
 * Shared, optionally lockable printer-location filter (Printers, Archives,
 * Maintenance).
 *
 * - Unlocked: the selection is page-local and resets when the page unmounts
 *   (previous behaviour of the Printers page).
 * - Locked: the selection is stored per browser in localStorage and applied on
 *   every page that uses this hook, also after a reload, until unlocked.
 *   Changing the location while locked updates the stored value.
 */

export const LOCATION_FILTER_ALL = 'all';

export const LOCATION_FILTER_STORAGE_KEY = 'locationFilter';
export const LOCATION_FILTER_LOCKED_STORAGE_KEY = 'locationFilterLocked';

/** Same-tab change notification (the native `storage` event only fires in other tabs). */
const CHANGE_EVENT = 'printbuddy:location-filter-change';

interface StoredState {
  locked: boolean;
  location: string;
}

function readStored(): StoredState {
  try {
    const locked = localStorage.getItem(LOCATION_FILTER_LOCKED_STORAGE_KEY) === 'true';
    const location = localStorage.getItem(LOCATION_FILTER_STORAGE_KEY);
    if (locked && location && location !== LOCATION_FILTER_ALL) {
      return { locked: true, location };
    }
  } catch {
    // Storage unavailable (private mode, blocked site data) — behave unlocked.
  }
  return { locked: false, location: LOCATION_FILTER_ALL };
}

function writeStored(state: StoredState | null) {
  try {
    if (state && state.locked) {
      localStorage.setItem(LOCATION_FILTER_LOCKED_STORAGE_KEY, 'true');
      localStorage.setItem(LOCATION_FILTER_STORAGE_KEY, state.location);
    } else {
      localStorage.removeItem(LOCATION_FILTER_LOCKED_STORAGE_KEY);
      localStorage.removeItem(LOCATION_FILTER_STORAGE_KEY);
    }
  } catch {
    // Ignore — the lock simply won't persist.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export interface LocationFilterState {
  /** Selected location, or LOCATION_FILTER_ALL. */
  location: string;
  setLocation: (location: string) => void;
  locked: boolean;
  /** Lock the current location / unlock. Locking "all" is a no-op. */
  setLocked: (locked: boolean) => void;
  /** True when a specific location is selected. */
  isActive: boolean;
  /** Predicate for filtering items by their printer's location. */
  matches: (printerLocation: string | null | undefined) => boolean;
}

/**
 * @param availableLocations Locations that currently exist. Pass `undefined`
 *   while still loading. When a locked or selected location no longer exists
 *   (renamed / last printer removed), the filter falls back to "all" and the
 *   lock is released so the page never stays silently empty.
 */
export function useLocationFilter(availableLocations?: readonly string[]): LocationFilterState {
  const [state, setState] = useState<StoredState>(readStored);

  // Follow lock changes made on another page in this tab or in another tab.
  useEffect(() => {
    const sync = () => {
      const stored = readStored();
      setState(prev => {
        if (stored.locked) return stored;
        // Lock was released elsewhere: keep the current selection page-local.
        return prev.locked ? { locked: false, location: prev.location } : prev;
      });
    };
    const onStorage = (e: StorageEvent) => {
      if (
        e.key === null ||
        e.key === LOCATION_FILTER_STORAGE_KEY ||
        e.key === LOCATION_FILTER_LOCKED_STORAGE_KEY
      ) {
        sync();
      }
    };
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  // Fall back when the selected location disappeared.
  const availableKey = availableLocations?.join('\u0000');
  useEffect(() => {
    if (!availableLocations) return;
    if (state.location === LOCATION_FILTER_ALL) return;
    if (availableLocations.includes(state.location)) return;
    if (state.locked) writeStored(null);
    setState({ locked: false, location: LOCATION_FILTER_ALL });
    // availableKey captures the list contents; the array identity may change every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableKey, state.location, state.locked]);

  const setLocation = useCallback((location: string) => {
    if (state.locked) {
      if (location === LOCATION_FILTER_ALL) {
        // Choosing "all" while locked releases the lock.
        setState({ locked: false, location: LOCATION_FILTER_ALL });
        writeStored(null);
        return;
      }
      setState({ locked: true, location });
      writeStored({ locked: true, location });
      return;
    }
    setState({ locked: false, location });
  }, [state.locked]);

  const setLocked = useCallback((locked: boolean) => {
    if (locked) {
      if (state.location === LOCATION_FILTER_ALL) return;
      setState({ locked: true, location: state.location });
      writeStored({ locked: true, location: state.location });
      return;
    }
    setState({ locked: false, location: state.location });
    writeStored(null);
  }, [state.location]);

  const { location, locked } = state;
  const isActive = location !== LOCATION_FILTER_ALL;
  const matches = useCallback(
    (printerLocation: string | null | undefined) =>
      location === LOCATION_FILTER_ALL || (printerLocation || '') === location,
    [location],
  );

  return { location, setLocation, locked, setLocked, isActive, matches };
}
