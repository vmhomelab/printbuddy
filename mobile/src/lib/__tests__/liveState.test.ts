import assert from 'node:assert/strict';
import { test } from 'node:test';

import { applyLiveMessage, parseLiveMessage, reconnectDelay } from '../liveState.ts';

test('parseLiveMessage ignores junk', () => {
  assert.equal(parseLiveMessage('not json'), null);
  assert.equal(parseLiveMessage('{"no":"type"}'), null);
  assert.equal(parseLiveMessage(42), null);
  assert.deepEqual(parseLiveMessage('{"type":"pong"}'), { type: 'pong' });
});

test('applyLiveMessage merges printer_status and leaves other messages alone', () => {
  const start = { 1: { connected: true, state: 'IDLE', progress: 0 } };
  const next = applyLiveMessage(start, { type: 'printer_status', printer_id: 1, data: { connected: true, state: 'RUNNING' } });
  assert.deepEqual(next[1], { connected: true, state: 'RUNNING', progress: 0 });
  assert.notEqual(next, start);
  assert.equal(applyLiveMessage(start, { type: 'pong' }), start);
  assert.equal(applyLiveMessage(start, { type: 'printer_status', printer_id: 'x' as unknown as number, data: { connected: true, state: null } }), start);
});

test('reconnectDelay backs off and caps at 30s', () => {
  assert.equal(reconnectDelay(0), 1000);
  assert.equal(reconnectDelay(3), 8000);
  assert.equal(reconnectDelay(20), 30000);
});
