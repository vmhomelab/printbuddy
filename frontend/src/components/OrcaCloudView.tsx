import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Cloud, ExternalLink, Loader2, LogOut, RefreshCw } from 'lucide-react';

import { api } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useAuth } from '../contexts/AuthContext';

/** Official Orca device-pairing and read-only profile browser. */
export function OrcaCloudView() {
  const queryClient = useQueryClient();
  const { hasPermission } = useAuth();
  const canManage = hasPermission('orca_cloud:auth');
  const [pairing, setPairing] = useState<Awaited<ReturnType<typeof api.orcaCloudDeviceStart>> | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const status = useQuery({ queryKey: ['orcaCloudStatus'], queryFn: api.orcaCloudStatus });
  const profiles = useQuery({
    queryKey: ['orcaCloudProfiles'], queryFn: api.orcaCloudListProfiles,
    enabled: status.data?.connected === true, retry: false,
  });
  const start = useMutation({
    mutationFn: api.orcaCloudDeviceStart,
    onSuccess: (data) => { setMessage(null); setPairing(data); },
    onError: (error: Error) => setMessage(error.message),
  });
  const logout = useMutation({
    mutationFn: api.orcaCloudLogout,
    onSuccess: () => { setPairing(null); queryClient.invalidateQueries({ queryKey: ['orcaCloudStatus'] }); queryClient.removeQueries({ queryKey: ['orcaCloudProfiles'] }); },
  });
  const poll = useQuery({
    queryKey: ['orcaCloudDevicePoll', pairing?.user_code ?? 'none'], queryFn: api.orcaCloudDevicePoll,
    enabled: pairing !== null, retry: false, refetchInterval: pairing ? Math.max(pairing.interval, 1) * 1000 : false,
  });
  useEffect(() => {
    if (!pairing || !poll.data) return;
    if (poll.data.status === 'complete') {
      setPairing(null);
      queryClient.invalidateQueries({ queryKey: ['orcaCloudStatus'] });
      queryClient.invalidateQueries({ queryKey: ['orcaCloudProfiles'] });
    } else if (poll.data.status === 'access_denied' || poll.data.status === 'expired_token') {
      setMessage(poll.data.status === 'access_denied' ? 'Orca Cloud pairing was denied.' : 'The Orca Cloud pairing code expired.');
      setPairing(null);
    }
  }, [pairing, poll.data, queryClient]);

  if (status.isLoading) return <div className="flex justify-center py-16"><Loader2 className="w-8 h-8 text-bambu-green animate-spin" /></div>;
  if (!status.data?.connected) return (
    <Card><CardContent className="p-8 max-w-xl mx-auto text-center">
      <Cloud className="w-12 h-12 text-bambu-green mx-auto mb-4" />
      <h2 className="text-xl font-semibold text-white">Connect Orca Cloud</h2>
      <p className="text-sm text-bambu-gray mt-2">Pair Printbuddy through Orca’s official approval flow. Printbuddy only requests read access to synced profiles; it never asks for your Orca password.</p>
      {message && <p className="mt-4 text-sm text-red-400">{message}</p>}
      {pairing ? <div className="mt-6 space-y-3">
        <p className="text-sm text-bambu-gray">Open Orca Cloud, approve this code, then return here.</p>
        <code className="block py-3 rounded bg-bambu-dark text-xl tracking-[0.25em] text-white">{pairing.user_code}</code>
        <a href={pairing.verification_uri_complete} target="_blank" rel="noreferrer"><Button className="w-full"><ExternalLink className="w-4 h-4" /> Open Orca Cloud approval</Button></a>
        <Button variant="secondary" className="w-full" onClick={() => setPairing(null)}>Cancel</Button>
      </div> : <Button className="mt-6" onClick={() => start.mutate()} disabled={!canManage || start.isPending}>{start.isPending && <Loader2 className="w-4 h-4 animate-spin" />} Connect Orca Cloud</Button>}
    </CardContent></Card>
  );
  const groups = [
    ['Filament', profiles.data?.filament ?? []], ['Process', profiles.data?.process ?? []], ['Printer', profiles.data?.printer ?? []],
  ] as const;
  return <div className="space-y-5">
    <div className="flex justify-between items-center p-3 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg"><span className="text-sm text-bambu-gray"><span className="inline-block w-2 h-2 mr-2 rounded-full bg-bambu-green" />Connected to Orca Cloud{status.data.email ? ` as ${status.data.email}` : ''}</span><Button variant="secondary" size="sm" disabled={!canManage || logout.isPending} onClick={() => logout.mutate()}><LogOut className="w-4 h-4" /> Disconnect</Button></div>
    <div className="flex justify-between items-center"><p className="text-sm text-bambu-gray">Read-only synced profiles. Select them when slicing from the modal.</p><Button variant="secondary" size="sm" onClick={() => profiles.refetch()} disabled={profiles.isFetching}><RefreshCw className={`w-4 h-4 ${profiles.isFetching ? 'animate-spin' : ''}`} /> Refresh</Button></div>
    {profiles.error ? <p className="text-red-400">{(profiles.error as Error).message}</p> : <div className="grid grid-cols-1 md:grid-cols-3 gap-5">{groups.map(([title, items]) => <Card key={title}><CardContent className="p-4"><h3 className="text-white font-medium mb-3">{title} <span className="text-bambu-gray">({items.length})</span></h3><div className="space-y-2">{items.length ? items.map(item => <div key={item.setting_id} className="rounded bg-bambu-dark px-3 py-2 text-sm text-bambu-gray">{item.name}</div>) : <p className="text-sm text-bambu-gray">No profiles</p>}</div></CardContent></Card>)}</div>}
  </div>;
}
