/**
 * Pairing link for the Printbuddy mobile app (vmhomelab/printbuddy-mobile-app):
 * printbuddy://pair?server=<url>&key=<api key>. Keep in sync with
 * parsePairingPayload in the app's src/lib/pairing.ts.
 */
export function buildPairingUri(serverUrl: string, apiKey: string): string {
  return `printbuddy://pair?server=${encodeURIComponent(serverUrl)}&key=${encodeURIComponent(apiKey)}`;
}

/** The address the phone should use: this page's origin plus any sub-path the app is served under. */
export function currentServerUrl(): string {
  const base = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '');
  return `${window.location.origin}${base}`;
}

const LOCAL_HOSTS = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\])$/i;

/** True when the address only works on this computer, so a phone could not use it. */
export function isLocalOnly(serverUrl: string): boolean {
  try {
    return LOCAL_HOSTS.test(new URL(serverUrl).hostname);
  } catch {
    return false;
  }
}
