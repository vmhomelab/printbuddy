import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Search } from 'lucide-react';
import { api, ApiError } from '../api/client';
import type { Printer, PrinterCreate, PrusaConnectLocalDevice } from '../api/client';
import { mapPrusaConnectLocalModel } from '../utils/prusaConnectLocal';
import { Button } from './Button';

const inputClass =
  'w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none';

function deviceLabel(device: PrusaConnectLocalDevice): string {
  return device.name || [device.model, device.serial].filter(Boolean).join(' ') || device.id;
}

export function PrusaConnectLocalAddSection({
  location,
  autoArchive,
  reconnectIntervalSeconds,
  onAdded,
}: {
  location?: string;
  autoArchive?: boolean;
  reconnectIntervalSeconds?: number;
  onAdded: (printers: Printer[], errors: string[]) => void;
}) {
  const { t } = useTranslation();
  const [host, setHost] = useState('');
  const [port, setPort] = useState('8080');
  const [apiKey, setApiKey] = useState('');
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState('');
  const [apiUrl, setApiUrl] = useState('');
  const [devices, setDevices] = useState<PrusaConnectLocalDevice[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);

  const selectable = useMemo(() => devices.filter((device) => !device.already_added), [devices]);

  const search = async () => {
    const trimmedHost = host.trim();
    if (!trimmedHost || !apiKey.trim()) {
      setError(t('printers.prusaConnectLocal.missingCredentials'));
      return;
    }
    setSearching(true);
    setError('');
    try {
      const portNumber = Number.parseInt(port, 10);
      const result = await api.discoverPrusaConnectLocalPrinters({
        host: trimmedHost,
        port: Number.isInteger(portNumber) && portNumber > 0 ? portNumber : undefined,
        api_key: apiKey.trim(),
      });
      setApiUrl(result.api_url);
      setDevices(result.printers);
      setSelected(new Set(result.printers.filter((device) => !device.already_added).map((device) => device.id)));
    } catch (e) {
      setDevices([]);
      setSelected(new Set());
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
      setSearched(true);
    }
  };

  const toggle = (id: string) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const addSelected = async () => {
    const chosen = devices.filter((device) => selected.has(device.id) && !device.already_added);
    if (chosen.length === 0) return;
    const created: Printer[] = [];
    const errors: string[] = [];
    setProgress({ done: 0, total: chosen.length });
    for (const [index, device] of chosen.entries()) {
      const payload: PrinterCreate = {
        name: deviceLabel(device).slice(0, 100),
        provider: 'prusaconnectlocal',
        ip_address: host.trim().split(':')[0],
        api_url: apiUrl,
        auth_token: apiKey.trim(),
        serial_number: device.printbuddy_serial,
        provider_options: JSON.stringify({
          pcl_device_id: device.id,
          pcl_serial: device.serial,
          pcl_vendor: device.vendor,
          pcl_model: device.model,
          ...(device.camera && {
            pcl_camera: device.camera.name,
            pcl_camera_stream: device.camera.stream,
            pcl_camera_snapshot: device.camera.snapshot,
          }),
        }),
        model: mapPrusaConnectLocalModel(device.model, device.vendor) || undefined,
        location: location || undefined,
        auto_archive: autoArchive ?? true,
        reconnect_interval_seconds: reconnectIntervalSeconds ?? 30,
        external_camera_enabled: false,
      };
      try {
        created.push(await api.createPrinter(payload));
      } catch (e) {
        const message = e instanceof ApiError || e instanceof Error ? e.message : String(e);
        errors.push(t('printers.prusaConnectLocal.addFailed', { name: deviceLabel(device), error: message }));
      }
      setProgress({ done: index + 1, total: chosen.length });
    }
    setProgress(null);
    const createdIds = new Set(created.map((printer) => printer.serial_number.toUpperCase()));
    setDevices((previous) =>
      previous.map((device) =>
        createdIds.has(device.printbuddy_serial.toUpperCase()) ? { ...device, already_added: true } : device,
      ),
    );
    setSelected(new Set());
    if (errors.length > 0) setError(errors.join('\n'));
    onAdded(created, errors);
  };

  const busy = searching || progress !== null;

  return (
    <div className="space-y-4">
      <p className="text-xs text-bambu-gray">{t('printers.prusaConnectLocal.description')}</p>
      <div className="flex gap-2">
        <div className="flex-1">
          <label htmlFor="pcl_host" className="block text-sm text-bambu-gray mb-1">
            {t('printers.prusaConnectLocal.serverIp')}
          </label>
          <input
            id="pcl_host"
            type="text"
            className={inputClass}
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="192.168.1.50"
            disabled={busy}
          />
        </div>
        <div className="w-24">
          <label htmlFor="pcl_port" className="block text-sm text-bambu-gray mb-1">
            {t('printers.prusaConnectLocal.port')}
          </label>
          <input
            id="pcl_port"
            type="number"
            min={1}
            max={65535}
            className={inputClass}
            value={port}
            onChange={(e) => setPort(e.target.value)}
            disabled={busy}
          />
        </div>
      </div>
      <div>
        <label htmlFor="pcl_api_key" className="block text-sm text-bambu-gray mb-1">
          {t('printers.prusaConnectLocal.apiKey')}
        </label>
        <input
          id="pcl_api_key"
          type="password"
          autoComplete="off"
          className={inputClass}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={t('printers.prusaConnectLocal.apiKeyPlaceholder')}
          disabled={busy}
        />
        <p className="text-xs text-bambu-gray mt-1">{t('printers.prusaConnectLocal.apiKeyHelp')}</p>
      </div>

      <Button type="button" variant="secondary" onClick={search} disabled={busy} className="w-full">
        {searching ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            {t('printers.prusaConnectLocal.searching')}
          </>
        ) : (
          <>
            <Search className="w-4 h-4" />
            {t('printers.prusaConnectLocal.searchPrinters')}
          </>
        )}
      </Button>

      {error && <div className="text-sm text-red-400 whitespace-pre-line">{error}</div>}

      {searched && !searching && !error && devices.length === 0 && (
        <p className="text-sm text-bambu-gray text-center">{t('printers.prusaConnectLocal.noPrinters')}</p>
      )}

      {devices.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-bambu-gray">
            <span>{t('printers.prusaConnectLocal.foundPrinters', { count: devices.length })}</span>
            <span className="flex gap-3">
              <button
                type="button"
                className="text-bambu-green hover:underline disabled:opacity-50"
                onClick={() => setSelected(new Set(selectable.map((device) => device.id)))}
                disabled={busy || selectable.length === 0}
              >
                {t('printers.prusaConnectLocal.selectAll')}
              </button>
              <button
                type="button"
                className="text-bambu-green hover:underline disabled:opacity-50"
                onClick={() => setSelected(new Set())}
                disabled={busy}
              >
                {t('printers.prusaConnectLocal.selectNone')}
              </button>
            </span>
          </div>
          <ul className="space-y-1 max-h-64 overflow-y-auto" data-testid="pcl-device-list">
            {devices.map((device) => {
              const checkboxId = `pcl_device_${device.id}`;
              return (
                <li key={device.id}>
                  <label
                    htmlFor={checkboxId}
                    className={`flex items-start gap-3 p-2 rounded-lg bg-bambu-dark transition-colors ${
                      device.already_added ? 'opacity-60 cursor-not-allowed' : 'hover:bg-bambu-dark-secondary cursor-pointer'
                    }`}
                  >
                    <input
                      id={checkboxId}
                      type="checkbox"
                      className="mt-1 rounded border-bambu-dark-tertiary bg-bambu-dark text-bambu-green focus:ring-bambu-green"
                      checked={device.already_added || selected.has(device.id)}
                      disabled={device.already_added || busy}
                      onChange={() => toggle(device.id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium text-white text-sm truncate">{deviceLabel(device)}</span>
                      <span className="block text-xs text-bambu-gray truncate">
                        {[device.vendor, device.model].filter(Boolean).join(' ') || '—'}
                        {device.serial && ` • SN ${device.serial}`}
                        {device.firmware && ` • FW ${device.firmware}`}
                      </span>
                      <span className="block text-xs truncate">
                        <span className={device.connected ? 'text-bambu-green' : 'text-yellow-500'}>
                          {device.connected ? device.state || 'online' : t('printers.prusaConnectLocal.offline')}
                        </span>
                        {!device.can_operate && (
                          <span className="text-yellow-500"> • {t('printers.prusaConnectLocal.readOnly')}</span>
                        )}
                        {device.camera && (
                          <span className="text-bambu-gray">
                            {' • '}
                            {t('printers.prusaConnectLocal.withCamera', { name: device.camera.name })}
                          </span>
                        )}
                        {device.already_added && (
                          <span className="text-bambu-gray"> • {t('printers.prusaConnectLocal.alreadyAdded')}</span>
                        )}
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {devices.length > 0 && (
        <Button type="button" onClick={addSelected} disabled={busy || selected.size === 0} className="w-full">
          {progress ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('printers.prusaConnectLocal.adding', progress)}
            </>
          ) : (
            t('printers.prusaConnectLocal.addSelected', { count: selected.size })
          )}
        </Button>
      )}
    </div>
  );
}
