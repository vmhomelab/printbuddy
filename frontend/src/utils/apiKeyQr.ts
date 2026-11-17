/**
 * Helpers for the API-key QR code.
 *
 * The QR encodes the Printbuddy base URL and the freshly-created API key together
 * so a mobile client can scan one code to configure both.
 *
 * Payload contract (fixed — bump `v` if it changes):
 *   printbuddy://config?v=1&url=<encodeURIComponent(baseUrl)>&key=<encodeURIComponent(apiKey)>
 */

/** Current payload schema version. */
export const API_KEY_QR_VERSION = 1;

/**
 * Build the QR payload string encoding the base URL + API key.
 *
 * @param baseUrl Origin a client uses to reach Printbuddy (origin only, no path).
 * @param apiKey  Raw API key string.
 */
export function buildApiKeyQrPayload(baseUrl: string, apiKey: string): string {
  return (
    `printbuddy://config?v=${API_KEY_QR_VERSION}` +
    `&url=${encodeURIComponent(baseUrl)}` +
    `&key=${encodeURIComponent(apiKey)}`
  );
}
