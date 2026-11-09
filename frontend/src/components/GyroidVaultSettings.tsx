import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Boxes, Check, Loader2, PlugZap, X } from 'lucide-react';
import { api, type GyroidVaultSettingsUpdate, type GyroidVaultTestResult } from '../api/client';
import { Card, CardContent, CardHeader } from './Card';
import { Button } from './Button';
import { Toggle } from './Toggle';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';

const inputClass =
  'w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white placeholder-bambu-gray/50 focus:border-bambu-green focus:outline-none';

/**
 * Settings card for the GyroidVault model-library integration.
 *
 * The API key is write-only: the backend only reports whether one is stored,
 * so the field stays empty and an empty value on save means "keep the key".
 */
export function GyroidVaultSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { hasPermission } = useAuth();
  const canUpdate = hasPermission('settings:update');

  const { data: settings, isLoading } = useQuery({
    queryKey: ['gyroidvault-settings'],
    queryFn: api.getGyroidVaultSettings,
  });

  const [enabled, setEnabled] = useState(false);
  const [url, setUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [testResult, setTestResult] = useState<GyroidVaultTestResult | null>(null);

  useEffect(() => {
    if (settings) {
      setEnabled(settings.enabled);
      setUrl(settings.url);
    }
  }, [settings]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['gyroidvault-settings'] });
    queryClient.invalidateQueries({ queryKey: ['gyroidvault-status'] });
    queryClient.invalidateQueries({ queryKey: ['settings'] });
  };

  const saveMutation = useMutation({
    mutationFn: (data: GyroidVaultSettingsUpdate) => api.updateGyroidVaultSettings(data),
    onSuccess: () => {
      setApiKey('');
      invalidate();
      showToast(t('gyroidvault.settings.saved'), 'success');
    },
    onError: (err: Error) => showToast(err.message || t('settings.toast.saveFailed'), 'error'),
  });

  const testMutation = useMutation({
    mutationFn: () =>
      api.testGyroidVaultConnection({
        url: url.trim() || undefined,
        api_key: apiKey.trim() || undefined,
      }),
    onSuccess: (result) => setTestResult(result),
    onError: (err: Error) =>
      setTestResult({
        ok: false,
        version: null,
        username: null,
        role: null,
        supported_version: true,
        warning: null,
        error: err.message,
      }),
  });

  const dirty =
    !!settings && (enabled !== settings.enabled || url.trim() !== settings.url || apiKey.trim() !== '');

  const handleSave = () => {
    const data: GyroidVaultSettingsUpdate = { enabled, url: url.trim() };
    if (apiKey.trim()) data.api_key = apiKey.trim();
    saveMutation.mutate(data);
  };

  return (
    <Card id="card-gyroidvault">
      <CardHeader>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Boxes className="w-5 h-5 text-bambu-green" />
            {t('gyroidvault.settings.title')}
          </h2>
          {canUpdate && <Toggle checked={enabled} onChange={setEnabled} disabled={isLoading} />}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-bambu-gray">{t('gyroidvault.settings.description')}</p>

        {isLoading ? (
          <div className="flex justify-center py-4">
            <Loader2 className="w-5 h-5 text-bambu-green animate-spin" />
          </div>
        ) : (
          <>
            <div>
              <label className="block text-sm text-white mb-1" htmlFor="gyroidvault-url">
                {t('gyroidvault.settings.url')}
              </label>
              <input
                id="gyroidvault-url"
                type="text"
                placeholder="http://192.168.1.50:3457"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={!canUpdate}
                className={inputClass}
                autoComplete="off"
              />
            </div>

            <div>
              <label className="block text-sm text-white mb-1" htmlFor="gyroidvault-api-key">
                {t('gyroidvault.settings.apiKey')}
              </label>
              <input
                id="gyroidvault-api-key"
                type="password"
                placeholder={
                  settings?.has_api_key
                    ? t('gyroidvault.settings.apiKeyStored')
                    : t('gyroidvault.settings.apiKeyPlaceholder')
                }
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={!canUpdate}
                className={inputClass}
                autoComplete="new-password"
              />
              <p className="text-xs text-bambu-gray mt-1">{t('gyroidvault.settings.apiKeyHint')}</p>
              {settings?.has_api_key && canUpdate && (
                <button
                  type="button"
                  className="text-xs text-red-400 hover:underline mt-1"
                  onClick={() => saveMutation.mutate({ api_key: '' })}
                >
                  {t('gyroidvault.settings.removeApiKey')}
                </button>
              )}
            </div>

            {testResult && (
              <div
                className={`rounded-lg border p-3 text-sm space-y-1 ${
                  testResult.ok ? 'border-bambu-green/40 bg-bambu-green/10' : 'border-red-500/40 bg-red-500/10'
                }`}
                data-testid="gyroidvault-test-result"
              >
                <p className="flex items-center gap-2 text-white">
                  {testResult.ok ? (
                    <Check className="w-4 h-4 text-bambu-green" />
                  ) : (
                    <X className="w-4 h-4 text-red-400" />
                  )}
                  {testResult.ok
                    ? t('gyroidvault.settings.testOk', {
                        version: testResult.version ?? '?',
                        user: testResult.username ?? '?',
                        role: testResult.role ?? '?',
                      })
                    : testResult.error}
                </p>
                {testResult.warning && (
                  <p className="flex items-start gap-2 text-amber-300">
                    <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                    {testResult.warning}
                  </p>
                )}
              </div>
            )}

            {canUpdate && (
              <div className="flex flex-wrap gap-2 justify-end">
                <Button
                  variant="secondary"
                  onClick={() => testMutation.mutate()}
                  disabled={testMutation.isPending || !url.trim()}
                >
                  {testMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <PlugZap className="w-4 h-4" />
                  )}
                  <span className="ml-2">{t('gyroidvault.settings.test')}</span>
                </Button>
                <Button variant="primary" onClick={handleSave} disabled={!dirty || saveMutation.isPending}>
                  {saveMutation.isPending && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
                  {t('gyroidvault.settings.save')}
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
