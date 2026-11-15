import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiError, NetworkError, PrintbuddyApi, authHeaders } from '../api.ts';

type Call = { url: string; init?: RequestInit };

function fakeFetch(response: Response | Error) {
  const calls: Call[] = [];
  const fetch = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (response instanceof Error) throw response;
    return response.clone();
  };
  return { fetch, calls };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

test('authHeaders per auth kind', () => {
  assert.deepEqual(authHeaders({ kind: 'none', token: null }), {});
  assert.deepEqual(authHeaders({ kind: 'jwt', token: 'abc' }), { Authorization: 'Bearer abc' });
  assert.deepEqual(authHeaders({ kind: 'apiKey', token: 'bb_x' }), { 'X-API-Key': 'bb_x' });
});

test('GET sends auth header to the versioned API path', async () => {
  const { fetch, calls } = fakeFetch(json([{ id: 1, name: 'X1C', is_active: true }]));
  const api = new PrintbuddyApi({ serverUrl: 'http://h:8000', kind: 'apiKey', token: 'bb_k' }, { fetch });
  const printers = await api.printers();
  assert.equal(printers[0]?.name, 'X1C');
  assert.equal(calls[0]?.url, 'http://h:8000/api/v1/printers/');
  assert.equal((calls[0]?.init?.headers as Record<string, string>)['X-API-Key'], 'bb_k');
  assert.equal(calls[0]?.init?.method, 'GET');
});

test('POST login sends JSON body', async () => {
  const { fetch, calls } = fakeFetch(json({ access_token: 't', token_type: 'bearer', user: null, requires_2fa: false, pre_auth_token: null, two_fa_methods: [] }));
  const api = new PrintbuddyApi({ serverUrl: 'http://h', kind: 'none', token: null }, { fetch });
  const res = await api.login('admin', 'pw');
  assert.equal(res.access_token, 't');
  assert.equal(calls[0]?.init?.body, JSON.stringify({ username: 'admin', password: 'pw' }));
  assert.equal((calls[0]?.init?.headers as Record<string, string>)['Content-Type'], 'application/json');
});

test('error responses become ApiError with FastAPI detail', async () => {
  const { fetch } = fakeFetch(json({ detail: 'Incorrect username or password' }, 401));
  const api = new PrintbuddyApi({ serverUrl: 'http://h', kind: 'none', token: null }, { fetch });
  await assert.rejects(api.login("a", "b"), (err: unknown) => {
    if (!(err instanceof ApiError)) return false;
    assert.equal(err.status, 401);
    assert.equal(err.isUnauthorized, true);
    assert.equal(err.detail, 'Incorrect username or password');
    return true;
  });
});

test('validation errors use the first message', async () => {
  const { fetch } = fakeFetch(json({ detail: [{ msg: 'too short' }] }, 422));
  const api = new PrintbuddyApi({ serverUrl: 'http://h', kind: 'none', token: null }, { fetch });
  await assert.rejects(api.verify2fa('p', '1', 'totp'), (err: unknown) => err instanceof ApiError && err.detail === 'too short');
});

test('fetch failures become NetworkError', async () => {
  const { fetch } = fakeFetch(new TypeError('Network request failed'));
  const api = new PrintbuddyApi({ serverUrl: 'http://h', kind: 'none', token: null }, { fetch });
  await assert.rejects(api.authStatus(), NetworkError);
});

test('camera token skipped without auth, snapshot URL carries token', async () => {
  const open = new PrintbuddyApi({ serverUrl: 'http://h', kind: 'none', token: null }, { fetch: fakeFetch(json({})).fetch });
  assert.equal(await open.cameraToken(), null);
  assert.equal(open.cameraSnapshotUrl(3, null, 5), 'http://h/api/v1/printers/3/camera/snapshot?t=5');

  const { fetch, calls } = fakeFetch(json({ token: 'cam' }));
  const authed = new PrintbuddyApi({ serverUrl: 'http://h', kind: 'jwt', token: 'j' }, { fetch });
  assert.equal(await authed.cameraToken(), 'cam');
  assert.equal(calls[0]?.url, 'http://h/api/v1/printers/camera/stream-token');
  assert.equal(authed.cameraSnapshotUrl(3, 'cam', 5), 'http://h/api/v1/printers/3/camera/snapshot?t=5&token=cam');
});
