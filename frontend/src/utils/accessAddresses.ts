/**
 * Access addresses: the URLs under which this Printbuddy instance is reachable
 * (LAN IP, Tailscale IP / MagicDNS name, public domain …).
 *
 * The connection kind is derived from the hostname alone, so the current
 * connection can be labelled even when no addresses are configured.
 */

export type ConnectionKind = 'lan' | 'tailscale' | 'public' | 'local';

export interface AccessAddress {
  name: string;
  url: string;
}

export const MAX_ACCESS_ADDRESSES = 10;

/** `scheme://host[:port]` for an http(s) URL, or null. Accepts input without scheme. */
export function normalizeOrigin(input: string): string | null {
  const raw = input.trim();
  if (!raw) return null;
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`;
  try {
    const u = new URL(withScheme);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    if (!u.hostname) return null;
    return u.origin;
  } catch {
    return null;
  }
}

function ipv4Parts(host: string): number[] | null {
  const m = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  return parts.every((p) => p <= 255) ? parts : null;
}

export function classifyHost(hostname: string): ConnectionKind {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (host.endsWith('.ts.net')) return 'tailscale';
  if (host === 'localhost') return 'local';
  if (host.endsWith('.local') || host.endsWith('.lan') || host.endsWith('.home.arpa')) return 'lan';
  if (host.startsWith('fd7a:115c:a1e0:')) return 'tailscale';
  if (host === '::1') return 'local';
  if (/^f[cd][0-9a-f]{2}:/.test(host) || host.startsWith('fe80:')) return 'lan';
  const ip = ipv4Parts(host);
  if (!ip) return 'public';
  const [a, b] = ip;
  if (a === 100 && b >= 64 && b <= 127) return 'tailscale'; // 100.64.0.0/10 (CGNAT, used by Tailscale)
  if (a === 127) return 'local';
  if (a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254)) return 'lan';
  return 'public';
}

export function classifyUrl(url: string): ConnectionKind {
  try {
    return classifyHost(new URL(url).hostname);
  } catch {
    return 'public';
  }
}

export function parseAccessAddresses(raw: string | null | undefined): AccessAddress[] {
  if (!raw) return [];
  try {
    const data: unknown = JSON.parse(raw);
    if (!Array.isArray(data)) return [];
    const out: AccessAddress[] = [];
    for (const item of data) {
      if (!item || typeof item !== 'object') continue;
      const rec = item as Record<string, unknown>;
      const origin = normalizeOrigin(String(rec.url ?? ''));
      if (!origin) continue;
      out.push({ name: String(rec.name ?? '').trim() || origin, url: origin });
    }
    return out.slice(0, MAX_ACCESS_ADDRESSES);
  } catch {
    return [];
  }
}

export function serializeAccessAddresses(list: AccessAddress[]): string {
  return JSON.stringify(list.map(({ name, url }) => ({ name, url })));
}

export function isCurrentOrigin(url: string, origin = window.location.origin): boolean {
  return normalizeOrigin(url) === origin;
}

/** Same page on another origin, e.g. https://box.ts.net/queue?x=1 */
export function switchUrl(targetOrigin: string, loc: Location = window.location): string {
  return `${targetOrigin}${loc.pathname}${loc.search}${loc.hash}`;
}

/**
 * Check from the browser whether an origin answers, by loading a tiny image
 * from it (the backend adds configured origins to the CSP img-src).
 *
 * Returns 'unknown' when the browser cannot tell — an http:// target from an
 * https:// page is blocked as mixed content before any request is made.
 */
export function probeOrigin(origin: string, timeoutMs = 3000): Promise<'reachable' | 'unreachable' | 'unknown'> {
  if (isCurrentOrigin(origin)) return Promise.resolve('reachable');
  if (window.location.protocol === 'https:' && origin.startsWith('http:')) return Promise.resolve('unknown');
  return new Promise((resolve) => {
    const img = new Image();
    const timer = window.setTimeout(() => {
      img.src = '';
      resolve('unreachable');
    }, timeoutMs);
    img.onload = () => {
      window.clearTimeout(timer);
      resolve('reachable');
    };
    img.onerror = () => {
      window.clearTimeout(timer);
      resolve('unreachable');
    };
    img.src = `${origin}/img/favicon-16x16.png?probe=${Date.now()}`;
  });
}
