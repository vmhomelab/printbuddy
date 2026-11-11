import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown, ChevronRight, Globe, Laptop, Network, Wifi, type LucideIcon } from 'lucide-react';
import { api } from '../api/client';
import {
  classifyHost,
  classifyUrl,
  isCurrentOrigin,
  parseAccessAddresses,
  probeOrigin,
  switchUrl,
  type ConnectionKind,
} from '../utils/accessAddresses';

const KIND_META: Record<ConnectionKind, { icon: LucideIcon; labelKey: string; fallback: string; className: string }> = {
  lan: { icon: Wifi, labelKey: 'connection.kind.lan', fallback: 'LAN', className: 'text-sky-400 bg-sky-400/10 border-sky-400/30' },
  tailscale: { icon: Network, labelKey: 'connection.kind.tailscale', fallback: 'Tailscale', className: 'text-violet-400 bg-violet-400/10 border-violet-400/30' },
  public: { icon: Globe, labelKey: 'connection.kind.public', fallback: 'Internet', className: 'text-amber-400 bg-amber-400/10 border-amber-400/30' },
  local: { icon: Laptop, labelKey: 'connection.kind.local', fallback: 'Local', className: 'text-bambu-gray-light bg-bambu-dark-tertiary border-bambu-dark-tertiary' },
};

type ProbeState = 'checking' | 'reachable' | 'unreachable' | 'unknown';

function useAccessAddresses() {
  const { data } = useQuery({ queryKey: ['ui-preferences'], queryFn: api.getUiPreferences, staleTime: 30_000 });
  return useMemo(() => parseAccessAddresses(data?.access_addresses), [data?.access_addresses]);
}

/** Small chip showing how the browser is connected right now (derived from the hostname). */
export function ConnectionBadge({ onClick }: { onClick?: () => void }) {
  const { t } = useTranslation();
  const addresses = useAccessAddresses();
  const kind = classifyHost(window.location.hostname);
  const current = addresses.find((a) => isCurrentOrigin(a.url));
  const meta = KIND_META[kind];
  const Icon = meta.icon;
  const label = current?.name ?? t(meta.labelKey, { defaultValue: meta.fallback });
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex max-w-[9rem] items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${meta.className}`}
      title={t('connection.current', { defaultValue: 'Current connection' }) + `: ${window.location.host}`}
    >
      <Icon className="h-3.5 w-3.5 flex-shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  );
}

/** Drawer section: current connection plus the configured alternatives to switch to. */
export function ConnectionSwitcher() {
  const { t } = useTranslation();
  const addresses = useAccessAddresses();
  const [probe, setProbe] = useState<Record<string, ProbeState>>({});
  const [expanded, setExpanded] = useState(false);
  const canSwitch = addresses.length > 1;

  useEffect(() => {
    if (!expanded) return;
    let cancelled = false;
    setProbe(Object.fromEntries(addresses.map((a) => [a.url, 'checking' as ProbeState])));
    for (const a of addresses) {
      probeOrigin(a.url).then((state) => {
        if (!cancelled) setProbe((prev) => ({ ...prev, [a.url]: state }));
      });
    }
    return () => {
      cancelled = true;
    };
  }, [addresses, expanded]);

  const currentKind = classifyHost(window.location.hostname);
  const CurrentIcon = KIND_META[currentKind].icon;

  return (
    <div className="mx-2 mb-2 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/40 p-2">
      <button
        type="button"
        onClick={() => canSwitch && setExpanded((v) => !v)}
        aria-expanded={expanded}
        className={`flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-left ${canSwitch ? 'hover:bg-bambu-dark-tertiary/50' : 'cursor-default'}`}
      >
        <CurrentIcon className="h-4 w-4 text-bambu-gray-light" />
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-wide text-bambu-gray">
            {t('connection.title', { defaultValue: 'Connection' })}
          </p>
          <p className="truncate text-sm text-white">{window.location.host}</p>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${KIND_META[currentKind].className}`}>
          {t(KIND_META[currentKind].labelKey, { defaultValue: KIND_META[currentKind].fallback })}
        </span>
        {canSwitch && (
          <ChevronDown className={`h-4 w-4 flex-shrink-0 text-bambu-gray transition-transform ${expanded ? 'rotate-180' : ''}`} />
        )}
      </button>

      {canSwitch && expanded && (
        <ul className="mt-1.5 max-h-[40vh] space-y-1 overflow-y-auto border-t border-bambu-dark-tertiary pt-1.5">
          {addresses.map((a) => {
            const current = isCurrentOrigin(a.url);
            const state = probe[a.url] ?? 'checking';
            const meta = KIND_META[classifyUrl(a.url)];
            const Icon = meta.icon;
            const dot =
              state === 'reachable' ? 'bg-status-ok' : state === 'unreachable' ? 'bg-status-error' : state === 'unknown' ? 'bg-bambu-gray' : 'bg-bambu-gray animate-pulse';
            const stateLabel = t(`connection.state.${state}`, {
              defaultValue: { checking: 'checking…', reachable: 'reachable', unreachable: 'not reachable', unknown: 'unknown' }[state],
            });
            return (
              <li key={a.url}>
                <button
                  type="button"
                  disabled={current}
                  onClick={() => {
                    window.location.href = switchUrl(a.url);
                  }}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-left transition-colors ${
                    current ? 'bg-bambu-green/10' : 'hover:bg-bambu-dark-tertiary active:bg-bambu-dark-tertiary'
                  }`}
                >
                  <Icon className="h-4 w-4 flex-shrink-0 text-bambu-gray-light" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-white">{a.name}</span>
                    <span className="flex items-center gap-1.5 text-[11px] text-bambu-gray">
                      <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} />
                      <span className="truncate">{current ? t('connection.connected', { defaultValue: 'connected' }) : stateLabel}</span>
                    </span>
                  </span>
                  {current ? (
                    <Check className="h-4 w-4 flex-shrink-0 text-bambu-green" />
                  ) : (
                    <ChevronRight className="h-4 w-4 flex-shrink-0 text-bambu-gray" />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
