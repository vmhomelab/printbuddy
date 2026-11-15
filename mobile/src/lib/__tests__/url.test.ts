import assert from 'node:assert/strict';
import { test } from 'node:test';

import { apiUrl, normalizeServerUrl, withQuery, wsUrl } from '../url.ts';

test('adds http:// when no scheme is given', () => {
  assert.equal(normalizeServerUrl('192.168.1.10:8000'), 'http://192.168.1.10:8000');
  assert.equal(normalizeServerUrl('  printbuddy.local  '), 'http://printbuddy.local');
});

test('keeps https and sub-paths, drops trailing slash, query and hash', () => {
  assert.equal(normalizeServerUrl('https://pb.example.com/'), 'https://pb.example.com');
  assert.equal(normalizeServerUrl('https://example.com/printbuddy///?x=1#y'), 'https://example.com/printbuddy');
});

test('rejects empty and non-http input', () => {
  assert.throws(() => normalizeServerUrl(''));
  assert.throws(() => normalizeServerUrl('ftp://host'));
  assert.throws(() => normalizeServerUrl('http://'));
});

test('builds API and WebSocket URLs', () => {
  assert.equal(apiUrl('http://h:8000', '/printers/'), 'http://h:8000/api/v1/printers/');
  assert.equal(apiUrl('http://h:8000', 'auth/status'), 'http://h:8000/api/v1/auth/status');
  assert.equal(wsUrl('http://h:8000'), 'ws://h:8000/api/v1/ws');
  assert.equal(wsUrl('https://pb.example.com/sub'), 'wss://pb.example.com/sub/api/v1/ws');
});

test('rejects hosts with spaces and bad ports, accepts IPv6 and lowercases', () => {
  assert.throws(() => normalizeServerUrl('nonsense host'));
  assert.throws(() => normalizeServerUrl('http://host:0'));
  assert.throws(() => normalizeServerUrl('http://host:70000'));
  assert.throws(() => normalizeServerUrl('http://-bad.example'));
  assert.equal(normalizeServerUrl('HTTPS://PB.Example.com:8443'), 'https://pb.example.com:8443');
  assert.equal(normalizeServerUrl('[fd00::1]:8000'), 'http://[fd00::1]:8000');
});

test('withQuery encodes and skips empty values', () => {
  assert.equal(withQuery('http://h/x', { t: 5, token: null }), 'http://h/x?t=5');
  assert.equal(withQuery('http://h/x', { token: 'a b&c' }), 'http://h/x?token=a%20b%26c');
  assert.equal(withQuery('http://h/x', {}), 'http://h/x');
});
