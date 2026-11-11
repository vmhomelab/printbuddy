import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { parseAccessAddresses } from '../utils/accessAddresses';
import { syncLauncherAddresses } from '../utils/launcher';

/** Keeps the phone launcher's copy of the access address list up to date. */
export function useLauncherSync(): void {
  const { data } = useQuery({ queryKey: ['ui-preferences'], queryFn: api.getUiPreferences, staleTime: 30_000 });
  const raw = data?.access_addresses;
  useEffect(() => {
    if (raw === undefined) return;
    syncLauncherAddresses(parseAccessAddresses(raw));
  }, [raw]);
}
