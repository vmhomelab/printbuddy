/**
 * Integration with the phone launcher (public/launch.html + launch.js).
 *
 * The installed app starts at /launch.html, which opens the first reachable
 * access address — directly when it is the launcher's own address, otherwise
 * inside a full-screen iframe. This module is the app side of that:
 *   - detects "embedded by the launcher" and switches to a layout where the
 *     main area scrolls (keeps the top bar fixed inside an iOS iframe)
 *   - applies the safe-area insets the launcher measured (env() is 0 in iframes)
 *   - hands the configured address list to the launcher
 *   - routes connection switches through the launcher so the home-screen app
 *     never drops into a Safari view
 *
 * Keep the protocol in sync with public/launch.js.
 */
import { isCurrentOrigin, normalizeOrigin, switchUrl, type AccessAddress } from './accessAddresses';

export const LAUNCHER_STORAGE_KEY = 'pb-launcher-addresses';
const EMBED_SESSION_KEY = 'pb-embedded-parent';

export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

let parentOrigin: string | null = null;

export function parseInsets(raw: string | null | undefined): Insets | null {
  if (!raw) return null;
  const parts = raw.split(',').map((p) => Number(p));
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n) || n < 0 || n > 200)) return null;
  const [top, right, bottom, left] = parts;
  return { top, right, bottom, left };
}

export function applyInsets(insets: Insets, root: HTMLElement = document.documentElement): void {
  root.style.setProperty('--safe-top', `${insets.top}px`);
  root.style.setProperty('--safe-right', `${insets.right}px`);
  root.style.setProperty('--safe-bottom', `${insets.bottom}px`);
  root.style.setProperty('--safe-left', `${insets.left}px`);
}

function detectParentOrigin(): string | null {
  const ancestors = (window.location as Location & { ancestorOrigins?: DOMStringList }).ancestorOrigins;
  if (ancestors && ancestors.length > 0) return normalizeOrigin(ancestors[0]);
  try {
    return document.referrer ? normalizeOrigin(document.referrer) : null;
  } catch {
    return null;
  }
}

/** Call once before React renders. */
export function initLauncherEmbedding(): void {
  if (window.self === window.top) return;

  const url = new URL(window.location.href);
  const flagged = url.searchParams.get('pb_embed') === '1';
  let stored: string | null = null;
  try {
    stored = sessionStorage.getItem(EMBED_SESSION_KEY);
  } catch {
    /* storage blocked */
  }
  if (!flagged && !stored) return; // framed by something else (e.g. Home Assistant)

  parentOrigin = stored || detectParentOrigin();
  if (!parentOrigin) return;
  try {
    sessionStorage.setItem(EMBED_SESSION_KEY, parentOrigin);
  } catch {
    /* storage blocked */
  }

  document.documentElement.classList.add('pb-embedded');
  const insets = parseInsets(url.searchParams.get('pb_insets'));
  if (insets) applyInsets(insets);

  if (flagged) {
    url.searchParams.delete('pb_embed');
    url.searchParams.delete('pb_insets');
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
  }

  window.addEventListener('message', (event) => {
    if (event.source !== window.parent || event.origin !== parentOrigin) return;
    const data = event.data as { source?: string; type?: string; insets?: unknown };
    if (data?.source !== 'pb-launcher' || data.type !== 'insets' || !data.insets) return;
    const i = data.insets as Record<string, unknown>;
    const parsed = parseInsets([i.top, i.right, i.bottom, i.left].join(','));
    if (parsed) applyInsets(parsed);
  });

  window.parent.postMessage({ source: 'pb-app', type: 'ready' }, parentOrigin);
}

export function isLauncherEmbedded(): boolean {
  return parentOrigin !== null;
}

function isStandalone(): boolean {
  return (
    window.matchMedia?.('(display-mode: standalone)').matches === true ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/** An https page cannot embed an http page (mixed content). */
export function canEmbed(targetOrigin: string, currentProtocol: string = window.location.protocol): boolean {
  return !(currentProtocol === 'https:' && targetOrigin.startsWith('http:'));
}

function trustedParent(addresses: AccessAddress[]): string | null {
  return parentOrigin && addresses.some((a) => a.url === parentOrigin) ? parentOrigin : null;
}

/** Give the launcher the current address list (it needs it before login). */
export function syncLauncherAddresses(addresses: AccessAddress[]): void {
  const payload = addresses.map(({ name, url }) => ({ name, url }));
  const parent = trustedParent(addresses);
  if (parent) {
    window.parent.postMessage({ source: 'pb-app', type: 'addresses', addresses: payload }, parent);
    return;
  }
  if (window.self !== window.top) return;
  try {
    if (payload.length) localStorage.setItem(LAUNCHER_STORAGE_KEY, JSON.stringify(payload));
    else localStorage.removeItem(LAUNCHER_STORAGE_KEY);
  } catch {
    /* storage blocked */
  }
}

/** Open the current page on another access address. */
export function switchToAddress(targetOrigin: string, addresses: AccessAddress[]): void {
  const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const parent = trustedParent(addresses);
  if (parent) {
    window.parent.postMessage({ source: 'pb-app', type: 'switch', url: targetOrigin, path }, parent);
    return;
  }
  if (window.self !== window.top) return; // framed, but not by a configured launcher
  const ownListed = addresses.some((a) => isCurrentOrigin(a.url));
  if (isStandalone() && ownListed && canEmbed(targetOrigin)) {
    // Stay inside the home-screen app: let the launcher embed the target.
    const params = new URLSearchParams({ to: targetOrigin, path });
    window.location.href = `/launch.html?${params.toString()}`;
    return;
  }
  window.location.href = switchUrl(targetOrigin);
}
