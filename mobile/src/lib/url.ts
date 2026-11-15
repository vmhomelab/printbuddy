// Deliberately no `new URL()` / URLSearchParams: React Native's polyfills for
// those are incomplete on device, and a web-only test would not notice.

const URL_RE = /^([a-z][a-z0-9+.-]*):\/\/([^/?#]*)([^?#]*)/i;
const HOST_RE =
  /^(\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*)(?::(\d{1,5}))?$/i;

/**
 * Turn whatever the user typed ("printbuddy.local:8000", "https://pb.example.com/")
 * into a canonical origin (plus optional sub-path) without a trailing slash.
 * Throws on input that can't be a server address.
 */
export function normalizeServerUrl(input: string): string {
  let value = input.trim();
  if (!value) throw new Error('empty');
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) value = `http://${value}`;

  const match = URL_RE.exec(value);
  if (!match) throw new Error('format');
  const scheme = match[1]!.toLowerCase();
  const authority = match[2]!;
  const rawPath = match[3]!;
  if (scheme !== 'http' && scheme !== 'https') throw new Error('protocol');

  const host = HOST_RE.exec(authority);
  if (!host) throw new Error('host');
  if (host[2] !== undefined && (Number(host[2]) < 1 || Number(host[2]) > 65535)) throw new Error('port');
  if (/\s/.test(rawPath)) throw new Error('path');

  // Keep a sub-path (reverse proxy under /printbuddy) but drop trailing slashes.
  const path = rawPath.replace(/\/+$/, '');
  return `${scheme}://${authority.toLowerCase()}${path}`;
}

export function apiUrl(serverUrl: string, path: string): string {
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${serverUrl}/api/v1${clean}`;
}

export function wsUrl(serverUrl: string): string {
  return `${serverUrl.replace(/^http/, 'ws')}/api/v1/ws`;
}

export function withQuery(url: string, params: Record<string, string | number | null | undefined>): string {
  const query = Object.entries(params)
    .filter((entry): entry is [string, string | number] => entry[1] !== null && entry[1] !== undefined)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
  return query ? `${url}?${query}` : url;
}
