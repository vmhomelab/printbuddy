import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link2, Plus, QrCode, Sparkles, Trash2, X } from 'lucide-react';
import { api } from '../api/client';
import { Card, CardContent, CardHeader } from './Card';
import {
  MAX_ACCESS_ADDRESSES,
  classifyUrl,
  isCurrentOrigin,
  normalizeOrigin,
  parseAccessAddresses,
  serializeAccessAddresses,
  type AccessAddress,
} from '../utils/accessAddresses';

const KIND_LABEL: Record<string, string> = { lan: 'LAN', tailscale: 'Tailscale', public: 'Internet', local: 'Local' };

interface Props {
  value: string;
  onChange: (value: string) => void;
}

export function AccessAddressesSettings({ value, onChange }: Props) {
  const { t } = useTranslation();
  const addresses = parseAccessAddresses(value);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [qr, setQr] = useState<{ name: string; url: string; image: string } | null>(null);

  const { data: suggestionData } = useQuery({
    queryKey: ['access-address-suggestions'],
    queryFn: api.getAccessAddressSuggestions,
    staleTime: 60_000,
  });

  const save = (list: AccessAddress[]) => onChange(serializeAccessAddresses(list));
  const origin = normalizeOrigin(url);
  const isDuplicate = (o: string) => addresses.some((a) => a.url === o);
  const full = addresses.length >= MAX_ACCESS_ADDRESSES;

  const add = (entry: AccessAddress) => {
    if (full || isDuplicate(entry.url)) return;
    save([...addresses, entry]);
  };

  const suggestions = [
    // The address the admin is using right now is always a good first entry
    { kind: classifyUrl(window.location.origin), name: KIND_LABEL[classifyUrl(window.location.origin)], url: window.location.origin },
    ...(suggestionData?.suggestions ?? []),
  ].filter((s, i, arr) => !isDuplicate(s.url) && arr.findIndex((x) => x.url === s.url) === i);

  const showQr = async (a: AccessAddress) => {
    const res = await api.getAccessAddressQRCode(a.url);
    setQr({ name: a.name, url: res.url, image: res.image });
  };

  return (
    <Card id="card-access-addresses">
      <CardHeader>
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Link2 className="w-5 h-5 text-blue-400" />
          {t('settings.accessAddresses.title', { defaultValue: 'Access addresses' })}
        </h2>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-bambu-gray">
          {t('settings.accessAddresses.description', {
            defaultValue:
              'Addresses Printbuddy is reachable under, e.g. LAN IP, Tailscale IP or a domain. Users can see which one they are connected through and switch from the menu. Each address keeps its own login.',
          })}
        </p>

        {/* Configured addresses */}
        {addresses.length > 0 && (
          <ul className="space-y-2">
            {addresses.map((a, idx) => {
              const kind = classifyUrl(a.url);
              return (
                <li key={a.url} className="flex items-center gap-2 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-2">
                  <div className="min-w-0 flex-1">
                    <input
                      value={a.name}
                      onChange={(e) => save(addresses.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
                      className="w-full bg-transparent text-sm font-medium text-white focus:outline-none"
                      aria-label={t('settings.accessAddresses.name', { defaultValue: 'Name' })}
                    />
                    <div className="flex items-center gap-2 text-xs text-bambu-gray">
                      <span className="rounded bg-bambu-dark-tertiary px-1.5 py-0.5">{KIND_LABEL[kind]}</span>
                      <span className="truncate">{a.url}</span>
                      {isCurrentOrigin(a.url) && (
                        <span className="text-bambu-green">{t('settings.accessAddresses.current', { defaultValue: 'current' })}</span>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => showQr(a)}
                    className="flex h-9 w-9 items-center justify-center rounded-lg text-bambu-gray hover:bg-bambu-dark-tertiary hover:text-white"
                    title={t('settings.accessAddresses.qr', { defaultValue: 'Show QR code' })}
                  >
                    <QrCode className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => save(addresses.filter((_, i) => i !== idx))}
                    className="flex h-9 w-9 items-center justify-center rounded-lg text-bambu-gray hover:bg-red-500/10 hover:text-red-400"
                    title={t('common.delete', { defaultValue: 'Delete' })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        {/* Suggestions */}
        {suggestions.length > 0 && !full && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs text-bambu-gray">
              <Sparkles className="h-3.5 w-3.5" />
              {t('settings.accessAddresses.suggestions', { defaultValue: 'Detected on this server' })}
            </p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button
                  key={s.url}
                  type="button"
                  onClick={() => add({ name: s.name, url: s.url })}
                  className="flex items-center gap-1.5 rounded-full border border-bambu-dark-tertiary px-3 py-1.5 text-xs text-bambu-gray-light hover:border-bambu-green hover:text-white"
                >
                  <Plus className="h-3 w-3" />
                  <span className="font-medium">{s.name}</span>
                  <span className="text-bambu-gray">{s.url.replace(/^https?:\/\//, '')}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Manual entry */}
        {!full && (
          <form
            className="flex flex-col gap-2 sm:flex-row"
            onSubmit={(e) => {
              e.preventDefault();
              if (!origin || isDuplicate(origin)) return;
              add({ name: name.trim() || KIND_LABEL[classifyUrl(origin)], url: origin });
              setName('');
              setUrl('');
            }}
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('settings.accessAddresses.namePlaceholder', { defaultValue: 'Name (e.g. Tailscale)' })}
              className="w-full sm:w-40 px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
            />
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://printbuddy.tailnet.ts.net"
              inputMode="url"
              autoCapitalize="none"
              className="w-full flex-1 px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
            />
            <button
              type="submit"
              disabled={!origin || isDuplicate(origin)}
              className="flex items-center justify-center gap-1.5 rounded-lg bg-bambu-green px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              <Plus className="h-4 w-4" />
              {t('common.add', { defaultValue: 'Add' })}
            </button>
          </form>
        )}
      </CardContent>

      {qr && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setQr(null)}>
          <div
            className="w-full max-w-xs rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary p-4 text-center"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-semibold text-white">{qr.name}</h3>
              <button type="button" onClick={() => setQr(null)} className="text-bambu-gray hover:text-white">
                <X className="h-5 w-5" />
              </button>
            </div>
            <img src={qr.image} alt={qr.url} className="mx-auto w-56 rounded-lg bg-white p-2" />
            <p className="mt-3 break-all text-sm text-bambu-gray">{qr.url}</p>
          </div>
        </div>
      )}
    </Card>
  );
}
