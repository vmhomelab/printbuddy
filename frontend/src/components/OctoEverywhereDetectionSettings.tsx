import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, ExternalLink, Info, Loader2, ShieldAlert, Sparkles, X } from 'lucide-react';
import {
  api,
  type OctoEverywhereAction,
  type OctoEverywhereSensitivity,
  type OctoEverywhereSettingsUpdate,
  type OctoEverywhereTestResult,
} from '../api/client';
import { Card, CardContent, CardHeader } from './Card';
import { Button } from './Button';
import { Toggle } from './Toggle';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';

const GADGET_API_KEY_URL = 'https://octoeverywhere.com/gadgetapi';
const INTERVAL_OPTIONS = [0, 10, 20, 30, 60, 120];
const selectClass = 'w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm';

const sameList = (a: number[] | null, b: number[] | null) =>
  a === b || (a !== null && b !== null && a.length === b.length && [...a].sort().join() === [...b].sort().join());

/**
 * Settings + status for the optional OctoEverywhere Gadget provider (PB-35).
 *
 * Independent of the Obico card above it: own settings, own status. The API
 * key is write-only — the backend only reports whether one is stored.
 */
export function OctoEverywhereDetectionSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { hasPermission } = useAuth();
  const canUpdate = hasPermission('settings:update');

  const { data: settings, isLoading } = useQuery({
    queryKey: ['octoeverywhere-settings'],
    queryFn: api.getOctoEverywhereSettings,
  });
  const { data: status } = useQuery({
    queryKey: ['octoeverywhere-status'],
    queryFn: api.getOctoEverywhereStatus,
    refetchInterval: 10000,
  });
  const { data: printers } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters });

  const [enabled, setEnabled] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [sensitivity, setSensitivity] = useState<OctoEverywhereSensitivity>('medium');
  const [action, setAction] = useState<OctoEverywhereAction>('notify');
  const [pollInterval, setPollInterval] = useState(0);
  const [notifyOnWarning, setNotifyOnWarning] = useState(true);
  const [enabledPrinters, setEnabledPrinters] = useState<number[] | null>(null);
  const [testResult, setTestResult] = useState<OctoEverywhereTestResult | null>(null);

  useEffect(() => {
    if (!settings) return;
    setEnabled(settings.enabled);
    setSensitivity(settings.sensitivity);
    setAction(settings.action);
    setPollInterval(settings.poll_interval);
    setNotifyOnWarning(settings.notify_on_warning);
    setEnabledPrinters(settings.enabled_printers);
  }, [settings]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['octoeverywhere-settings'] });
    queryClient.invalidateQueries({ queryKey: ['octoeverywhere-status'] });
  };

  const saveMutation = useMutation({
    mutationFn: (data: OctoEverywhereSettingsUpdate) => api.updateOctoEverywhereSettings(data),
    onSuccess: () => {
      setApiKey('');
      invalidate();
      showToast(t('settings.toast.settingsSaved'), 'success');
    },
    onError: (err: Error) => showToast(err.message || t('settings.toast.saveFailed'), 'error'),
  });

  const testMutation = useMutation({
    mutationFn: () => api.testOctoEverywhereConnection(apiKey.trim() || undefined),
    onSuccess: (result) => setTestResult(result),
    onError: (err: Error) => setTestResult({ ok: false, error_type: null, error: err.message }),
  });

  const dirty =
    !!settings &&
    (enabled !== settings.enabled ||
      sensitivity !== settings.sensitivity ||
      action !== settings.action ||
      pollInterval !== settings.poll_interval ||
      notifyOnWarning !== settings.notify_on_warning ||
      !sameList(enabledPrinters, settings.enabled_printers) ||
      apiKey.trim() !== '');

  const handleSave = () => {
    const data: OctoEverywhereSettingsUpdate = {
      enabled,
      sensitivity,
      action,
      poll_interval: pollInterval,
      notify_on_warning: notifyOnWarning,
    };
    if (enabledPrinters === null) data.all_printers = true;
    else data.enabled_printers = enabledPrinters;
    if (apiKey.trim()) data.api_key = apiKey.trim();
    saveMutation.mutate(data);
  };

  const togglePrinter = (printerId: number, checked: boolean) => {
    const current = enabledPrinters ?? printers?.map((p) => p.id) ?? [];
    setEnabledPrinters(checked ? [...new Set([...current, printerId])] : current.filter((id) => id !== printerId));
  };

  const issueLabel = (issue: string | null) => {
    switch (issue) {
      case 'no_camera':
        return t('octoeverywhereDetection.issueNoCamera');
      case 'viewer_busy':
        return t('octoeverywhereDetection.issueViewerBusy');
      case 'capture_failed':
        return t('octoeverywhereDetection.issueCaptureFailed');
      default:
        return issue;
    }
  };

  const formDisabled = !canUpdate;

  return (
    <div className="flex flex-col lg:flex-row gap-4 lg:gap-6 mt-4">
      <div className="space-y-3 flex-1 lg:max-w-xl">
        <Card id="card-fd-octoeverywhere">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-bambu-green" />
                <h2 className="text-lg font-semibold text-white">{t('octoeverywhereDetection.title')}</h2>
              </div>
              {canUpdate && (
                <div aria-label={t('octoeverywhereDetection.title')}>
                  <Toggle checked={enabled} onChange={setEnabled} disabled={isLoading} />
                </div>
              )}
            </div>
            <p className="text-sm text-bambu-gray mt-2">{t('octoeverywhereDetection.description')}</p>
          </CardHeader>
          <CardContent className="space-y-4">
            {isLoading ? (
              <div className="flex justify-center py-4">
                <Loader2 className="w-5 h-5 text-bambu-green animate-spin" />
              </div>
            ) : (
              <>
                <div className="flex items-start gap-2 p-3 bg-blue-900/20 border border-blue-800 rounded text-xs text-blue-200">
                  <ShieldAlert className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>{t('octoeverywhereDetection.privacyNote')}</span>
                </div>

                <div>
                  <label className="block text-sm text-bambu-gray mb-1" htmlFor="octoeverywhere-api-key">
                    {t('octoeverywhereDetection.apiKey')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      id="octoeverywhere-api-key"
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={
                        settings?.has_api_key
                          ? t('octoeverywhereDetection.apiKeyStored')
                          : t('octoeverywhereDetection.apiKeyPlaceholder')
                      }
                      disabled={formDisabled}
                      autoComplete="new-password"
                      className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white text-sm"
                    />
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setTestResult(null);
                        testMutation.mutate();
                      }}
                      disabled={formDisabled || testMutation.isPending || (!apiKey.trim() && !settings?.has_api_key)}
                    >
                      {testMutation.isPending ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        t('octoeverywhereDetection.test')
                      )}
                    </Button>
                  </div>
                  <p className="text-xs text-bambu-gray mt-1">
                    {t('octoeverywhereDetection.apiKeyHint')}{' '}
                    <a
                      href={GADGET_API_KEY_URL}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-bambu-green hover:underline"
                    >
                      {t('octoeverywhereDetection.getApiKey')}
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </p>
                  {settings?.has_api_key && canUpdate && (
                    <button
                      type="button"
                      className="text-xs text-red-400 hover:underline mt-1"
                      onClick={() => saveMutation.mutate({ api_key: '' })}
                    >
                      {t('octoeverywhereDetection.removeApiKey')}
                    </button>
                  )}
                  {testResult && (
                    <div
                      className={`flex items-start gap-2 mt-2 text-sm ${testResult.ok ? 'text-green-400' : 'text-red-400'}`}
                    >
                      {testResult.ok ? <Check className="w-4 h-4 mt-0.5" /> : <X className="w-4 h-4 mt-0.5" />}
                      <span>
                        {testResult.ok
                          ? t('octoeverywhereDetection.testSuccess')
                          : testResult.error || t('octoeverywhereDetection.testFailed')}
                      </span>
                    </div>
                  )}
                </div>

                <div>
                  <label className="block text-sm text-bambu-gray mb-1" htmlFor="octoeverywhere-sensitivity">
                    {t('failureDetection.sensitivity')}
                  </label>
                  <select
                    id="octoeverywhere-sensitivity"
                    value={sensitivity}
                    onChange={(e) => setSensitivity(e.target.value as OctoEverywhereSensitivity)}
                    disabled={formDisabled}
                    className={selectClass}
                  >
                    <option value="low">{t('failureDetection.sensitivityLow')}</option>
                    <option value="medium">{t('failureDetection.sensitivityMedium')}</option>
                    <option value="high">{t('failureDetection.sensitivityHigh')}</option>
                  </select>
                  <p className="text-xs text-bambu-gray mt-1">{t('octoeverywhereDetection.sensitivityHint')}</p>
                </div>

                <div>
                  <label className="block text-sm text-bambu-gray mb-1" htmlFor="octoeverywhere-action">
                    {t('octoeverywhereDetection.action')}
                  </label>
                  <select
                    id="octoeverywhere-action"
                    value={action}
                    onChange={(e) => setAction(e.target.value as OctoEverywhereAction)}
                    disabled={formDisabled}
                    className={selectClass}
                  >
                    <option value="notify">{t('failureDetection.actionNotify')}</option>
                    <option value="pause">{t('failureDetection.actionPause')}</option>
                    <option value="pause_and_off">{t('failureDetection.actionPauseOff')}</option>
                  </select>
                  <p className="text-xs text-bambu-gray mt-1">{t('octoeverywhereDetection.actionHint')}</p>
                </div>

                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm text-white">{t('octoeverywhereDetection.notifyOnWarning')}</p>
                    <p className="text-xs text-bambu-gray">{t('octoeverywhereDetection.notifyOnWarningHint')}</p>
                  </div>
                  <div aria-label={t('octoeverywhereDetection.notifyOnWarning')}>
                    <Toggle checked={notifyOnWarning} onChange={setNotifyOnWarning} disabled={formDisabled} />
                  </div>
                </div>

                <div>
                  <label className="block text-sm text-bambu-gray mb-1" htmlFor="octoeverywhere-interval">
                    {t('octoeverywhereDetection.interval')}
                  </label>
                  <select
                    id="octoeverywhere-interval"
                    value={pollInterval}
                    onChange={(e) => setPollInterval(Number(e.target.value))}
                    disabled={formDisabled}
                    className={selectClass}
                  >
                    {INTERVAL_OPTIONS.map((sec) => (
                      <option key={sec} value={sec}>
                        {sec === 0
                          ? t('octoeverywhereDetection.intervalAuto')
                          : t('octoeverywhereDetection.intervalSeconds', { seconds: sec })}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-bambu-gray mt-1">{t('octoeverywhereDetection.intervalHint')}</p>
                </div>

                <div>
                  <p className="text-sm text-bambu-gray mb-1">{t('failureDetection.perPrinterTitle')}</p>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={enabledPrinters === null}
                      onChange={(e) => setEnabledPrinters(e.target.checked ? null : (printers?.map((p) => p.id) ?? []))}
                      disabled={formDisabled}
                    />
                    <span className="text-white">{t('failureDetection.monitorAll')}</span>
                  </label>
                  {enabledPrinters !== null && printers && (
                    <div className="pl-5 mt-1 space-y-1 border-l border-gray-700">
                      {printers.map((p) => (
                        <label key={p.id} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={enabledPrinters.includes(p.id)}
                            onChange={(e) => togglePrinter(p.id, e.target.checked)}
                            disabled={formDisabled}
                          />
                          <span className="text-white">{p.name}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>

                {enabled && settings && !settings.has_api_key && !apiKey.trim() && (
                  <div className="flex items-start gap-2 p-3 bg-amber-900/30 border border-amber-700 rounded text-sm text-amber-200">
                    <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                    <span>{t('octoeverywhereDetection.apiKeyMissing')}</span>
                  </div>
                )}

                {canUpdate && (
                  <div className="flex justify-end">
                    <Button onClick={handleSave} disabled={!dirty || saveMutation.isPending}>
                      {saveMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                      {t('octoeverywhereDetection.save')}
                    </Button>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="space-y-3 flex-1 lg:max-w-xl">
        <Card id="card-fd-octoeverywhere-status">
          <CardHeader>
            <h2 className="text-lg font-semibold text-white">{t('octoeverywhereDetection.statusTitle')}</h2>
          </CardHeader>
          <CardContent>
            {!status ? (
              <div className="flex items-center gap-2 text-bambu-gray">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>{t('common.loading')}</span>
              </div>
            ) : (
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-bambu-gray">{t('failureDetection.serviceRunning')}</span>
                  <span className={status.is_running ? 'text-green-400' : 'text-red-400'}>
                    {status.is_running ? t('common.yes') : t('common.no')}
                  </span>
                </div>
                {status.account_error && (
                  <div className="flex items-start gap-2 text-amber-300">
                    <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                    <span>{t('octoeverywhereDetection.accountError', { error: status.account_error })}</span>
                  </div>
                )}
                {status.last_error && (
                  <div className="flex items-start gap-2 text-red-400">
                    <X className="w-4 h-4 mt-0.5 flex-shrink-0" />
                    <span className="break-words">{status.last_error}</span>
                  </div>
                )}
                <div>
                  <div className="text-bambu-gray mb-1">{t('failureDetection.activePrinters')}</div>
                  {Object.keys(status.per_printer).length === 0 ? (
                    <div className="text-bambu-gray italic text-xs">{t('failureDetection.noActivePrints')}</div>
                  ) : (
                    <div className="space-y-1">
                      {Object.entries(status.per_printer).map(([pid, info]) => {
                        const printer = printers?.find((p) => String(p.id) === pid);
                        const colorClass = info.pause
                          ? 'text-red-400'
                          : info.warning
                            ? 'text-amber-400'
                            : 'text-green-400';
                        return (
                          <div key={pid} className="flex justify-between gap-2">
                            <span className="text-white">{printer?.name ?? `Printer ${pid}`}</span>
                            <span className={`font-mono text-right ${colorClass}`}>
                              {info.stopped_reason
                                ? t('octoeverywhereDetection.stopped', { reason: info.stopped_reason })
                                : info.last_issue && info.print_quality === null
                                  ? issueLabel(info.last_issue)
                                  : info.print_quality !== null
                                    ? t('octoeverywhereDetection.quality', { value: info.print_quality })
                                    : t('octoeverywhereDetection.waiting')}
                              {info.pause
                                ? ` · ${t('octoeverywhereDetection.flagPause')}`
                                : info.warning
                                  ? ` · ${t('octoeverywhereDetection.flagWarning')}`
                                  : ''}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card id="card-fd-octoeverywhere-history">
          <CardHeader>
            <h2 className="text-lg font-semibold text-white">{t('octoeverywhereDetection.historyTitle')}</h2>
          </CardHeader>
          <CardContent>
            {!status || status.history.length === 0 ? (
              <div className="flex items-center gap-2 text-bambu-gray text-sm">
                <Info className="w-4 h-4" />
                <span>{t('failureDetection.noHistory')}</span>
              </div>
            ) : (
              <div className="space-y-1 max-h-96 overflow-y-auto text-xs font-mono">
                {status.history.map((ev, idx) => {
                  const printer = printers?.find((p) => p.id === ev.printer_id);
                  const colorClass = ev.pause ? 'text-red-400' : ev.warning ? 'text-amber-400' : 'text-bambu-gray';
                  const label = ev.pause
                    ? t('octoeverywhereDetection.flagPause')
                    : ev.warning
                      ? t('octoeverywhereDetection.flagWarning')
                      : t('octoeverywhereDetection.quality', { value: ev.print_quality ?? '?' });
                  return (
                    <div key={idx} className="flex justify-between gap-2 py-1 border-b border-gray-800">
                      <span className="text-bambu-gray">{new Date(ev.timestamp).toLocaleTimeString()}</span>
                      <span className="text-white truncate">{printer?.name ?? `#${ev.printer_id}`}</span>
                      <span className={colorClass}>{label}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
