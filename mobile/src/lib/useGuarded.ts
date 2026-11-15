import { useCallback } from 'react';

import { ApiError } from './api.ts';
import { useSession } from './session.tsx';

/**
 * Wraps an API call so a 401 drops the user back to the sign-in screen
 * instead of leaving them on a screen that can never load.
 */
export function useGuarded() {
  const { markExpired, session } = useSession();
  return useCallback(
    async <T>(fn: () => Promise<T>): Promise<T> => {
      try {
        return await fn();
      } catch (err) {
        if (err instanceof ApiError && err.isUnauthorized && session?.kind !== 'none') markExpired();
        throw err;
      }
    },
    [markExpired, session?.kind],
  );
}
