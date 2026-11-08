import { afterEach, describe, expect, it, vi } from 'vitest';
import { uuidV4 } from '../../utils/random';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('uuidV4', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns a v4 UUID', () => {
    expect(uuidV4()).toMatch(UUID_V4);
  });

  it('falls back to getRandomValues when randomUUID is missing (plain-HTTP LAN access)', () => {
    vi.stubGlobal('crypto', {
      getRandomValues: (bytes: Uint8Array) => bytes.fill(0xff),
    });
    expect(uuidV4()).toBe('ffffffff-ffff-4fff-bfff-ffffffffffff');
  });

  it('falls back to Math.random without any crypto API', () => {
    vi.stubGlobal('crypto', undefined);
    const ids = new Set(Array.from({ length: 20 }, () => uuidV4()));
    for (const id of ids) expect(id).toMatch(UUID_V4);
    expect(ids.size).toBe(20);
  });
});
