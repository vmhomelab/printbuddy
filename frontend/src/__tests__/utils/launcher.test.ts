import { afterEach, describe, expect, it, vi } from 'vitest';
import { LAUNCHER_STORAGE_KEY, applyInsets, parseInsets, syncLauncherAddresses } from '../../utils/launcher';
import { classifyHost, normalizeOrigin, parseAccessAddresses } from '../../utils/accessAddresses';

describe('parseInsets', () => {
  it('parses four non-negative numbers', () => {
    expect(parseInsets('47,0,34,0')).toEqual({ top: 47, right: 0, bottom: 34, left: 0 });
  });

  it('rejects malformed or implausible values', () => {
    expect(parseInsets(null)).toBeNull();
    expect(parseInsets('47,0,34')).toBeNull();
    expect(parseInsets('a,b,c,d')).toBeNull();
    expect(parseInsets('-1,0,0,0')).toBeNull();
    expect(parseInsets('9999,0,0,0')).toBeNull();
  });
});

describe('applyInsets', () => {
  it('overrides the safe-area CSS variables', () => {
    const el = document.createElement('div');
    applyInsets({ top: 47, right: 1, bottom: 34, left: 2 }, el);
    expect(el.style.getPropertyValue('--safe-top')).toBe('47px');
    expect(el.style.getPropertyValue('--safe-bottom')).toBe('34px');
    expect(el.style.getPropertyValue('--safe-left')).toBe('2px');
  });
});

describe('syncLauncherAddresses (top-level)', () => {
  afterEach(() => vi.clearAllMocks());

  it('stores the list for the launcher on this origin', () => {
    syncLauncherAddresses([{ name: 'LAN', url: 'http://192.168.1.10:8000' }]);
    expect(localStorage.setItem).toHaveBeenCalledWith(
      LAUNCHER_STORAGE_KEY,
      JSON.stringify([{ name: 'LAN', url: 'http://192.168.1.10:8000' }]),
    );
  });

  it('clears the list when no addresses are configured', () => {
    syncLauncherAddresses([]);
    expect(localStorage.removeItem).toHaveBeenCalledWith(LAUNCHER_STORAGE_KEY);
  });

  it('does not post to a parent when not embedded', () => {
    const spy = vi.spyOn(window.parent, 'postMessage');
    syncLauncherAddresses([{ name: 'LAN', url: 'http://192.168.1.10:8000' }]);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe('access address helpers', () => {
  it('normalizes input with or without scheme', () => {
    expect(normalizeOrigin('192.168.1.10:8000/queue')).toBe('http://192.168.1.10:8000');
    expect(normalizeOrigin('https://box.tail1234.ts.net/')).toBe('https://box.tail1234.ts.net');
    expect(normalizeOrigin('javascript:alert(1)')).toBeNull();
  });

  it('classifies connection kinds', () => {
    expect(classifyHost('100.101.102.103')).toBe('tailscale');
    expect(classifyHost('box.tail1234.ts.net')).toBe('tailscale');
    expect(classifyHost('192.168.1.10')).toBe('lan');
    expect(classifyHost('printbuddy.example.com')).toBe('public');
    expect(classifyHost('127.0.0.1')).toBe('local');
  });

  it('drops invalid stored entries', () => {
    expect(
      parseAccessAddresses('[{"name":"ok","url":"http://10.0.0.1"},{"name":"bad","url":"ftp://x"},"junk"]'),
    ).toEqual([{ name: 'ok', url: 'http://10.0.0.1' }]);
    expect(parseAccessAddresses('not json')).toEqual([]);
  });
});
