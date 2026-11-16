/**
 * The live-update WebSocket must carry the auth token (the backend rejects
 * unauthenticated handshakes when auth is enabled). Browsers can't set headers,
 * so the token goes in as a subprotocol next to "printbuddy.v1".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { openAuthenticatedWebSocket, setAuthToken } from '../../api/client';

const calls: { url: string; protocols?: string | string[] }[] = [];
const originalWebSocket = globalThis.WebSocket;

class RecordingWebSocket {
  constructor(url: string, protocols?: string | string[]) {
    calls.push({ url, protocols });
  }
}

describe('openAuthenticatedWebSocket', () => {
  beforeEach(() => {
    calls.length = 0;
    globalThis.WebSocket = RecordingWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    setAuthToken(null);
    globalThis.WebSocket = originalWebSocket;
    vi.restoreAllMocks();
  });

  it('connects without subprotocols when signed out (auth disabled)', () => {
    setAuthToken(null);
    openAuthenticatedWebSocket('ws://host/api/v1/ws');
    expect(calls).toEqual([{ url: 'ws://host/api/v1/ws', protocols: undefined }]);
  });

  it('sends the token as a bearer subprotocol', () => {
    setAuthToken('eyJhbGciOi.payload.sig');
    openAuthenticatedWebSocket('wss://host/api/v1/ws');
    expect(calls).toEqual([
      { url: 'wss://host/api/v1/ws', protocols: ['printbuddy.v1', 'bearer.eyJhbGciOi.payload.sig'] },
    ]);
  });

  it('falls back to a plain connection when the browser rejects the subprotocol', () => {
    setAuthToken('bad token');
    let first = true;
    globalThis.WebSocket = class {
      constructor(url: string, protocols?: string | string[]) {
        if (first && protocols) {
          first = false;
          throw new DOMException('invalid subprotocol', 'SyntaxError');
        }
        calls.push({ url, protocols });
      }
    } as unknown as typeof WebSocket;
    openAuthenticatedWebSocket('ws://host/api/v1/ws');
    expect(calls).toEqual([{ url: 'ws://host/api/v1/ws', protocols: undefined }]);
  });
});
