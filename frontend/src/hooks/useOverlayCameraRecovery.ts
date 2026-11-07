import { useCallback, useEffect, useRef, useState } from 'react';

// MJPEG <img> connections can stop delivering frames without firing onError.
// Renew only the camera connection, keeping the overlay and its credentials.
// This also renews healthy connections; it does not measure frame freshness.
const STREAM_RENEWAL_MS = 60_000;
const ERROR_RETRY_MS = 3_000;

export function useOverlayCameraRecovery(enabled: boolean) {
  const [imageKey, setImageKey] = useState(Date.now);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const renew = useCallback(() => {
    if (retryTimer.current !== null) {
      clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
    setImageKey((key) => key + 1);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    // Start a fresh deadline after each retry so a newly opened connection
    // isn't immediately replaced by the previous connection's renewal timer.
    const renewalTimer = setTimeout(renew, STREAM_RENEWAL_MS);
    return () => {
      clearTimeout(renewalTimer);
      if (retryTimer.current !== null) {
        clearTimeout(retryTimer.current);
        retryTimer.current = null;
      }
    };
  }, [enabled, imageKey, renew]);

  const handleStreamError = useCallback(() => {
    if (!enabled || retryTimer.current !== null) return;
    retryTimer.current = setTimeout(renew, ERROR_RETRY_MS);
  }, [enabled, renew]);

  return { imageKey, handleStreamError };
}
