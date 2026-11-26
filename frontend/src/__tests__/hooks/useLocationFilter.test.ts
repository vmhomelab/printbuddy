/**
 * Tests for the shared, lockable location filter hook.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import {
  useLocationFilter,
  LOCATION_FILTER_ALL,
  LOCATION_FILTER_STORAGE_KEY,
  LOCATION_FILTER_LOCKED_STORAGE_KEY,
} from '../../hooks/useLocationFilter';

const LOCATIONS = ['Site A', 'Site B'];

describe('useLocationFilter', () => {
  let store: Map<string, string>;

  beforeEach(() => {
    store = new Map();
    vi.mocked(localStorage.getItem).mockImplementation((key: string) => store.get(key) ?? null);
    vi.mocked(localStorage.setItem).mockImplementation((key: string, value: string) => {
      store.set(key, value);
    });
    vi.mocked(localStorage.removeItem).mockImplementation((key: string) => {
      store.delete(key);
    });
  });

  afterEach(() => {
    vi.mocked(localStorage.getItem).mockReset();
    vi.mocked(localStorage.setItem).mockReset();
    vi.mocked(localStorage.removeItem).mockReset();
  });

  it('starts unlocked on "all" with nothing stored', () => {
    const { result } = renderHook(() => useLocationFilter(LOCATIONS));
    expect(result.current.location).toBe(LOCATION_FILTER_ALL);
    expect(result.current.locked).toBe(false);
    expect(result.current.isActive).toBe(false);
    expect(result.current.matches('Site A')).toBe(true);
    expect(result.current.matches(null)).toBe(true);
  });

  it('keeps an unlocked selection page-local (not persisted, reset on remount)', () => {
    const { result, unmount } = renderHook(() => useLocationFilter(LOCATIONS));
    act(() => result.current.setLocation('Site A'));
    expect(result.current.location).toBe('Site A');
    expect(result.current.matches('Site A')).toBe(true);
    expect(result.current.matches('Site B')).toBe(false);
    expect(result.current.matches(null)).toBe(false);
    expect(store.size).toBe(0);
    unmount();

    const { result: again } = renderHook(() => useLocationFilter(LOCATIONS));
    expect(again.current.location).toBe(LOCATION_FILTER_ALL);
  });

  it('persists a locked location and restores it on the next mount', () => {
    const { result, unmount } = renderHook(() => useLocationFilter(LOCATIONS));
    act(() => result.current.setLocation('Site B'));
    act(() => result.current.setLocked(true));
    expect(result.current.locked).toBe(true);
    expect(store.get(LOCATION_FILTER_LOCKED_STORAGE_KEY)).toBe('true');
    expect(store.get(LOCATION_FILTER_STORAGE_KEY)).toBe('Site B');
    unmount();

    const { result: again } = renderHook(() => useLocationFilter(LOCATIONS));
    expect(again.current.location).toBe('Site B');
    expect(again.current.locked).toBe(true);
  });

  it('updates the stored value when the location changes while locked', () => {
    store.set(LOCATION_FILTER_LOCKED_STORAGE_KEY, 'true');
    store.set(LOCATION_FILTER_STORAGE_KEY, 'Site A');
    const { result } = renderHook(() => useLocationFilter(LOCATIONS));
    act(() => result.current.setLocation('Site B'));
    expect(result.current.locked).toBe(true);
    expect(store.get(LOCATION_FILTER_STORAGE_KEY)).toBe('Site B');
  });

  it('releases the lock when "all" is chosen while locked', () => {
    store.set(LOCATION_FILTER_LOCKED_STORAGE_KEY, 'true');
    store.set(LOCATION_FILTER_STORAGE_KEY, 'Site A');
    const { result } = renderHook(() => useLocationFilter(LOCATIONS));
    act(() => result.current.setLocation(LOCATION_FILTER_ALL));
    expect(result.current.locked).toBe(false);
    expect(store.size).toBe(0);
  });

  it('unlocking clears storage but keeps the current selection on this page', () => {
    store.set(LOCATION_FILTER_LOCKED_STORAGE_KEY, 'true');
    store.set(LOCATION_FILTER_STORAGE_KEY, 'Site A');
    const { result } = renderHook(() => useLocationFilter(LOCATIONS));
    act(() => result.current.setLocked(false));
    expect(result.current.locked).toBe(false);
    expect(result.current.location).toBe('Site A');
    expect(store.size).toBe(0);
  });

  it('cannot lock "all"', () => {
    const { result } = renderHook(() => useLocationFilter(LOCATIONS));
    act(() => result.current.setLocked(true));
    expect(result.current.locked).toBe(false);
    expect(store.size).toBe(0);
  });

  it('ignores a stored value that is not locked', () => {
    store.set(LOCATION_FILTER_STORAGE_KEY, 'Site A');
    const { result } = renderHook(() => useLocationFilter(LOCATIONS));
    expect(result.current.location).toBe(LOCATION_FILTER_ALL);
  });

  it('falls back to "all" and unlocks when the locked location no longer exists', () => {
    store.set(LOCATION_FILTER_LOCKED_STORAGE_KEY, 'true');
    store.set(LOCATION_FILTER_STORAGE_KEY, 'Old Site');
    const { result } = renderHook(() => useLocationFilter(LOCATIONS));
    expect(result.current.location).toBe(LOCATION_FILTER_ALL);
    expect(result.current.locked).toBe(false);
    expect(store.size).toBe(0);
  });

  it('keeps a locked location while the location list is still loading', () => {
    store.set(LOCATION_FILTER_LOCKED_STORAGE_KEY, 'true');
    store.set(LOCATION_FILTER_STORAGE_KEY, 'Site A');
    const { result, rerender } = renderHook(
      ({ locations }: { locations?: string[] }) => useLocationFilter(locations),
      { initialProps: { locations: undefined as string[] | undefined } },
    );
    expect(result.current.location).toBe('Site A');
    rerender({ locations: LOCATIONS });
    expect(result.current.location).toBe('Site A');
    expect(result.current.locked).toBe(true);
  });

  it('syncs lock changes between hook instances in the same tab', () => {
    const a = renderHook(() => useLocationFilter(LOCATIONS));
    const b = renderHook(() => useLocationFilter(LOCATIONS));
    act(() => a.result.current.setLocation('Site A'));
    act(() => a.result.current.setLocked(true));
    expect(b.result.current.location).toBe('Site A');
    expect(b.result.current.locked).toBe(true);

    act(() => a.result.current.setLocked(false));
    expect(b.result.current.locked).toBe(false);
  });

  it('survives localStorage throwing', () => {
    vi.mocked(localStorage.getItem).mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.mocked(localStorage.setItem).mockImplementation(() => {
      throw new Error('blocked');
    });
    const { result } = renderHook(() => useLocationFilter(LOCATIONS));
    act(() => result.current.setLocation('Site A'));
    act(() => result.current.setLocked(true));
    expect(result.current.location).toBe('Site A');
  });
});
