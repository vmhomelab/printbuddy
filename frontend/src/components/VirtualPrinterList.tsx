import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus, Printer, ExternalLink, AlertTriangle, FileText, ShieldCheck, Copy, Check, Download, Plug } from 'lucide-react';
import { multiVirtualPrinterApi, virtualPrinterApi } from '../api/client';
import { Card, CardContent } from './Card';
import { Button } from './Button';
import { Toggle } from './Toggle';
import { useToast } from '../contexts/ToastContext';
import { copyTextToClipboard, downloadTextFile } from '../utils/clipboard';
import { VIRTUAL_PRINTER_SETUP_GUIDE_URL } from '../constants/documentation';
import { VirtualPrinterCard } from './VirtualPrinterCard';
import { VirtualPrinterAddDialog } from './VirtualPrinterAddDialog';

export function VirtualPrinterList() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [showAddDialog, setShowAddDialog] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['virtual-printers'],
    queryFn: multiVirtualPrinterApi.list,
    refetchInterval: 10000,
  });

  const { data: globalSettings } = useQuery({
    queryKey: ['virtual-printer-settings'],
    queryFn: virtualPrinterApi.getSettings,
  });

  const archiveNameSourceMutation = useMutation({
    mutationFn: (source: 'metadata' | 'filename') =>
      virtualPrinterApi.updateSettings({ archive_name_source: source }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['virtual-printer-settings'] });
      showToast(t('virtualPrinter.toast.updated'));
    },
    onError: (error: Error) => {
      showToast(error.message || t('virtualPrinter.toast.failedToUpdate'), 'error');
    },
  });

  const useFilename = globalSettings?.archive_name_source === 'filename';

  // Shared CA certificate — the slicer imports it once to trust every VP's
  // TLS connection. Generated on demand by the backend, never changes.
  const { data: caCert } = useQuery({
    queryKey: ['vp-ca-certificate'],
    queryFn: multiVirtualPrinterApi.getCaCertificate,
    staleTime: Infinity,
  });
  const [caCopied, setCaCopied] = useState(false);

  const handleCopyCert = async () => {
    if (!caCert) return;
    const ok = await copyTextToClipboard(caCert.pem);
    if (ok) {
      setCaCopied(true);
      showToast(t('virtualPrinter.caCert.copied'));
      setTimeout(() => setCaCopied(false), 2000);
    } else {
      showToast(t('virtualPrinter.toast.copyFailed'), 'error');
    }
  };

  const handleDownloadCert = () => {
    if (!caCert) return;
    downloadTextFile(caCert.pem, 'printbuddy-virtual-printer-ca.crt', 'application/x-pem-file');
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8 flex justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-bambu-green" />
        </CardContent>
      </Card>
    );
  }

  const printers = data?.printers || [];
  const models = data?.models || {};

  return (
    <div className="space-y-4">
      {/* Supported virtual printer types (#52): Bambu-compatible VPs emulate a
          Bambu printer and need network setup; Moonraker/OctoPrint-compatible
          VPs are an HTTP upload endpoint on the Printbuddy port. */}
      <Card>
        <CardContent className="py-4 px-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base text-white font-semibold">{t('virtualPrinter.types.title')}</h2>
            <span className="inline-flex items-center rounded-full border border-bambu-green/60 bg-bambu-green/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-bambu-green">
              {t('virtualPrinter.types.newBadge')}
            </span>
          </div>
          <p className="text-xs text-bambu-gray">{t('virtualPrinter.types.intro')}</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-stretch">
            {/* Bambu-compatible */}
            <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-4 flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Printer className="w-4 h-4 text-bambu-green flex-shrink-0" />
                <p className="text-sm text-white font-semibold">{t('virtualPrinter.protocol.bambu')}</p>
                <span className="ml-auto text-[10px] text-bambu-gray-light bg-bambu-dark-tertiary rounded px-2 py-0.5">
                  {t('virtualPrinter.types.bambu.tag')}
                </span>
              </div>
              <ul className="space-y-1 list-disc pl-4 text-xs text-bambu-gray">
                <li>{t('virtualPrinter.types.bambu.point1')}</li>
                <li>{t('virtualPrinter.types.bambu.point2')}</li>
                <li>{t('virtualPrinter.types.bambu.point3')}</li>
              </ul>
              <div className="mt-auto flex items-start gap-2 rounded-md border border-yellow-500/50 bg-yellow-500/10 px-3 py-2">
                <AlertTriangle className="w-4 h-4 text-yellow-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-white">
                  <span className="font-semibold text-yellow-400">{t('virtualPrinter.types.bambu.setupLabel')}</span>{' '}
                  {t('virtualPrinter.types.bambu.setupText')}{' '}
                  <a
                    href={VIRTUAL_PRINTER_SETUP_GUIDE_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-bambu-green underline hover:text-bambu-green-light"
                  >
                    {t('virtualPrinter.types.bambu.guide')}
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </p>
              </div>
            </div>

            {/* Moonraker/OctoPrint-compatible */}
            <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-4 flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Plug className="w-4 h-4 text-bambu-green flex-shrink-0" />
                <p className="text-sm text-white font-semibold">{t('virtualPrinter.protocol.moonraker')}</p>
                <span className="ml-auto text-[10px] text-bambu-gray-light bg-bambu-dark-tertiary rounded px-2 py-0.5">
                  {t('virtualPrinter.types.moonraker.tag')}
                </span>
              </div>
              <ul className="space-y-1 list-disc pl-4 text-xs text-bambu-gray">
                <li>{t('virtualPrinter.types.moonraker.point1')}</li>
                <li>{t('virtualPrinter.types.moonraker.point2')}</li>
                <li>{t('virtualPrinter.types.moonraker.point3')}</li>
              </ul>
              <div className="mt-auto flex items-start gap-2 rounded-md border border-bambu-green/50 bg-bambu-green/10 px-3 py-2">
                <Check className="w-4 h-4 text-bambu-green flex-shrink-0 mt-0.5" />
                <p className="text-xs text-white">
                  <span className="font-semibold text-bambu-green">{t('virtualPrinter.types.moonraker.noSetupLabel')}</span>{' '}
                  {t('virtualPrinter.types.moonraker.noSetupText')}
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Global VP behavior settings — two side-by-side cards, not full width */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
        {/* Slicer CA certificate — shared by every VP, imported into the
            slicer's trust store once instead of fetching it from the CLI. */}
        <Card>
          <CardContent className="py-3 px-4">
            <div className="flex items-start gap-3">
              <ShieldCheck className="w-4 h-4 text-bambu-green flex-shrink-0 mt-1" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2 min-w-0">
                    <p className="text-sm text-white font-medium">
                      {t('virtualPrinter.caCert.title')}
                    </p>
                    <span className="text-[10px] text-bambu-gray-light bg-bambu-dark-tertiary rounded px-2 py-0.5">
                      {t('virtualPrinter.caCert.bambuOnlyBadge')}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      onClick={handleCopyCert}
                      disabled={!caCert}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-bambu-dark-secondary border border-bambu-dark-tertiary text-white hover:border-bambu-gray disabled:opacity-50 transition-colors"
                    >
                      {caCopied
                        ? <Check className="w-3.5 h-3.5 text-bambu-green" />
                        : <Copy className="w-3.5 h-3.5" />}
                      {caCopied ? t('virtualPrinter.caCert.copied') : t('virtualPrinter.caCert.copy')}
                    </button>
                    <button
                      onClick={handleDownloadCert}
                      disabled={!caCert}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-bambu-dark-secondary border border-bambu-dark-tertiary text-white hover:border-bambu-gray disabled:opacity-50 transition-colors"
                    >
                      <Download className="w-3.5 h-3.5" />
                      {t('virtualPrinter.caCert.download')}
                    </button>
                  </div>
                </div>
                <p className="text-xs text-bambu-gray mt-1">
                  {t('virtualPrinter.caCert.description')}
                </p>
                {caCert && (
                  <p
                    className="text-[10px] text-bambu-gray font-mono mt-1 truncate"
                    title={caCert.fingerprint_sha256}
                  >
                    {t('virtualPrinter.caCert.fingerprint')}: {caCert.fingerprint_sha256}
                  </p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Archive name source */}
        <Card>
          <CardContent className="py-3 px-4">
            <div className="flex items-start gap-3">
              <FileText className="w-4 h-4 text-bambu-green flex-shrink-0 mt-1" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-white font-medium">
                    {t('virtualPrinter.archiveNameSource.title')}
                  </p>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className={`text-xs ${useFilename ? 'text-bambu-gray' : 'text-white'}`}>
                      {t('virtualPrinter.archiveNameSource.metadata')}
                    </span>
                    <Toggle
                      checked={useFilename}
                      onChange={(checked) => archiveNameSourceMutation.mutate(checked ? 'filename' : 'metadata')}
                      disabled={archiveNameSourceMutation.isPending}
                    />
                    <span className={`text-xs ${useFilename ? 'text-white' : 'text-bambu-gray'}`}>
                      {t('virtualPrinter.archiveNameSource.filename')}
                    </span>
                  </div>
                </div>
                <p className="text-xs text-bambu-gray mt-1">
                  {t('virtualPrinter.archiveNameSource.description')}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Header with add button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Printer className="w-5 h-5 text-bambu-green" />
          <h2 className="text-lg font-semibold text-white">{t('virtualPrinter.list.title')}</h2>
          <span className="text-sm text-bambu-gray">({printers.length})</span>
        </div>
        <Button variant="primary" onClick={() => setShowAddDialog(true)}>
          <Plus className="w-4 h-4 mr-1" />
          {t('virtualPrinter.list.add')}
        </Button>
      </div>

      {/* Printer cards - 3 column grid */}
      {printers.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center">
            <Printer className="w-12 h-12 text-bambu-gray mx-auto mb-3" />
            <p className="text-bambu-gray mb-4">{t('virtualPrinter.list.empty')}</p>
            <Button variant="primary" onClick={() => setShowAddDialog(true)}>
              <Plus className="w-4 h-4 mr-1" />
              {t('virtualPrinter.list.addFirst')}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-start">
          {printers.map((printer) => (
            <VirtualPrinterCard key={printer.id} printer={printer} models={models} />
          ))}
        </div>
      )}

      {showAddDialog && (
        <VirtualPrinterAddDialog onClose={() => setShowAddDialog(false)} />
      )}
    </div>
  );
}
