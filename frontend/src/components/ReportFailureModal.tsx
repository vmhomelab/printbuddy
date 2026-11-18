import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Flag, Loader2, Settings, X } from 'lucide-react';
import { api, ApiError } from '../api/client';
import type { CustomFailureReason, Printer } from '../api/client';
import { Card, CardContent } from './Card';
import { Button } from './Button';
import { FailureReasonIcon } from './FailureReasonIcon';
import { FailureReasonSettings } from './FailureReasonSettings';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';
import {
  customFailureReasonSubtitle,
  customFailureReasonTitle,
  formatIsoDay,
  reasonGridColumns,
} from '../utils/customFailure';

interface ReportFailureModalProps {
  printer: Pick<Printer, 'id' | 'name'>;
  onClose: () => void;
}

const TILE_MIN_WIDTH = 150;
const TILE_GAP = 8;
const MODAL_PADDING = 48 + 32; // card padding + screen margin

function useWindowWidth(): number {
  const [width, setWidth] = useState(() => (typeof window === 'undefined' ? 1024 : window.innerWidth));
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return width;
}

/**
 * "Report failed print": flag the printer's current (or most recent) print with a
 * reason, picked from a grid of tiles. The cog opens the reason settings.
 * Separate from the automatic failure_reason on archives.
 */
export function ReportFailureModal({ printer, onClose }: ReportFailureModalProps) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { hasPermission } = useAuth();
  const canWithdraw = hasPermission('archives:delete_all');
  const canEditReasons = hasPermission('settings:update');
  const windowWidth = useWindowWidth();
  const [showSettings, setShowSettings] = useState(false);

  const {
    data: target,
    isLoading: targetLoading,
    error: targetError,
  } = useQuery({
    queryKey: ['customFailureTarget', printer.id],
    queryFn: () => api.getCustomFailureReportTarget(printer.id),
    retry: false,
  });
  const { data: allReasons = [], isLoading: reasonsLoading } = useQuery({
    queryKey: ['customFailureReasons'],
    queryFn: () => api.getCustomFailureReasons({ includeHidden: true }),
  });

  const existing = target?.existing_report ?? null;
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  // Empty by default on purpose: nobody has to put their name on a failed print.
  const [reportedBy, setReportedBy] = useState('');
  const [initialised, setInitialised] = useState(false);

  // Fill the form once the data is there (later refetches must not undo the user's choice).
  useEffect(() => {
    if (initialised || !target) return;
    if (existing) {
      setReason(existing.custom_failure_reason);
      setComment(existing.comment ?? '');
      setReportedBy(existing.reported_by ?? '');
    }
    setInitialised(true);
  }, [initialised, target, existing]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Visible reasons, plus the existing report's reason if it was hidden meanwhile.
  const selectable: CustomFailureReason[] = allReasons.filter(
    (r) => !r.is_hidden || r.code === existing?.custom_failure_reason
  );
  const columns = reasonGridColumns(selectable.length, windowWidth - MODAL_PADDING, TILE_MIN_WIDTH + TILE_GAP);
  // Tiles are ~200 px wide when there is room, enough for a 3-line subtitle of ~90 characters.
  const reportWidth = Math.max(448, columns * (TILE_MIN_WIDTH + 62) + 48);
  const cardWidth = showSettings ? 640 : reportWidth;

  const refreshStats = () => {
    queryClient.invalidateQueries({ queryKey: ['customFailureStats'] });
    queryClient.invalidateQueries({ queryKey: ['customFailureReports'] });
    queryClient.invalidateQueries({ queryKey: ['customFailureTarget'] });
  };

  const saveMutation = useMutation({
    mutationFn: () =>
      api.createCustomFailureReport({
        printer_id: printer.id,
        archive_id: target!.archive_id,
        custom_failure_reason: reason,
        comment,
        reported_by: reportedBy,
      }),
    onSuccess: () => {
      refreshStats();
      showToast(t('customFailure.modal.saved'), 'success');
      onClose();
    },
    onError: (error: Error) => showToast(error.message || t('customFailure.modal.saveFailed'), 'error'),
  });

  const withdrawMutation = useMutation({
    mutationFn: () => api.deleteCustomFailureReport(existing!.id),
    onSuccess: () => {
      refreshStats();
      showToast(t('customFailure.modal.withdrawn'), 'success');
      onClose();
    },
    onError: (error: Error) => showToast(error.message || t('customFailure.modal.saveFailed'), 'error'),
  });

  const busy = saveMutation.isPending || withdrawMutation.isPending;
  const noPrintYet = targetError instanceof ApiError && targetError.status === 404;
  const existingReason = allReasons.find((r) => r.code === existing?.custom_failure_reason);
  const existingTitle = existing ? customFailureReasonTitle(t, existing.custom_failure_reason, existingReason) : '';
  // The print this report applies to.
  const print = target
    ? {
        archiveId: target.archive_id,
        hasThumbnail: target.has_thumbnail,
        label: `${target.is_current_print ? t('customFailure.modal.currentPrint') : t('customFailure.modal.lastPrint')} · ${printer.name}`,
        name: target.print_name || target.filename || '–',
        filename: target.filename,
        date: target.print_started_at,
      }
    : null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={busy ? undefined : onClose}>
      <Card
        className="w-full max-h-[calc(100vh-2rem)] overflow-y-auto"
        style={{ maxWidth: cardWidth }}
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
      >
        <CardContent className="p-6">
          <div className="flex items-start justify-between gap-3 mb-4">
            <h3 className="text-lg font-semibold text-white flex items-center gap-2">
              {showSettings ? (
                <>
                  <button
                    type="button"
                    onClick={() => setShowSettings(false)}
                    className="p-1 -ml-1 hover:bg-bambu-dark rounded"
                    aria-label={t('customFailure.settings.back')}
                    title={t('customFailure.settings.back')}
                  >
                    <ArrowLeft className="w-5 h-5 text-bambu-gray" />
                  </button>
                  {t('customFailure.settings.title')}
                </>
              ) : (
                <>
                  <Flag className="w-5 h-5 text-red-400" />
                  {t('customFailure.modal.title')}
                </>
              )}
            </h3>
            <div className="flex items-center gap-1">
              {canEditReasons && !showSettings && (
                <button
                  type="button"
                  onClick={() => setShowSettings(true)}
                  className="p-1 hover:bg-bambu-dark rounded"
                  aria-label={t('customFailure.settings.open')}
                  title={t('customFailure.settings.open')}
                >
                  <Settings className="w-5 h-5 text-bambu-gray" />
                </button>
              )}
              <button onClick={onClose} className="p-1 hover:bg-bambu-dark rounded" aria-label={t('common.close')}>
                <X className="w-5 h-5 text-bambu-gray" />
              </button>
            </div>
          </div>

          {showSettings ? (
            <FailureReasonSettings reasons={allReasons} />
          ) : targetLoading || reasonsLoading ? (
            <div className="flex justify-center py-6">
              <Loader2 className="w-6 h-6 text-bambu-green animate-spin" />
            </div>
          ) : !print ? (
            <p className="text-sm text-bambu-gray">
              {noPrintYet ? t('customFailure.modal.noPrint') : (targetError as Error | null)?.message}
            </p>
          ) : (
            <div className="space-y-4">
              {/* Which print this report applies to */}
              <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/60 p-3 flex items-center gap-3">
                {print.hasThumbnail && print.archiveId != null && (
                  <img
                    src={api.getArchiveThumbnail(print.archiveId)}
                    alt=""
                    className="w-14 h-14 object-contain rounded bg-bambu-dark flex-shrink-0"
                  />
                )}
                <div className="min-w-0">
                  <div className="text-xs text-bambu-gray">{print.label}</div>
                  <div className="text-sm font-medium text-white truncate" title={print.filename ?? undefined}>
                    {print.name}
                  </div>
                  <div className="text-xs text-bambu-gray">{formatIsoDay(print.date)}</div>
                </div>
              </div>

              {existing && (
                <p className="text-xs text-yellow-400">
                  {t('customFailure.modal.alreadyReported', { reason: existingTitle })}
                </p>
              )}

              <div role="radiogroup" aria-label={t('customFailure.modal.reason')}>
                <div className="text-sm text-bambu-gray mb-2">{t('customFailure.modal.reason')}</div>
                <div
                  className="grid"
                  style={{
                    gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
                    gridAutoRows: '1fr',
                    gap: TILE_GAP,
                  }}
                >
                  {selectable.map((r) => {
                    const selected = reason === r.code;
                    const title = customFailureReasonTitle(t, r.code, r);
                    const subtitle = customFailureReasonSubtitle(t, r.code, r);
                    return (
                      <button
                        key={r.code}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => setReason(r.code)}
                        title={subtitle ? `${title}: ${subtitle}` : title}
                        className={`flex flex-col items-center text-center gap-1 rounded-lg border p-3 min-h-[8.5rem] transition-colors ${
                          selected
                            ? 'border-bambu-green bg-bambu-green/15'
                            : 'border-bambu-dark-tertiary bg-bambu-dark/60 hover:border-bambu-gray'
                        } ${r.is_hidden ? 'opacity-60' : ''}`}
                      >
                        <FailureReasonIcon
                          reason={r}
                          className={`w-9 h-9 flex-shrink-0 ${selected ? 'text-bambu-green' : 'text-bambu-gray'}`}
                        />
                        <span
                          lang={i18n.language}
                          className="w-full text-sm font-bold text-white leading-tight line-clamp-2 hyphens-auto break-words"
                        >
                          {title}
                        </span>
                        {subtitle && (
                          <span
                            lang={i18n.language}
                            className="w-full text-xs text-bambu-gray leading-snug line-clamp-3 hyphens-auto break-words"
                          >
                            {subtitle}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label htmlFor="custom-failure-comment" className="block text-sm text-bambu-gray mb-1">
                  {t('customFailure.modal.comment')}
                </label>
                <textarea
                  id="custom-failure-comment"
                  rows={3}
                  maxLength={2000}
                  className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder={t('customFailure.modal.commentPlaceholder')}
                />
              </div>

              <div>
                <label htmlFor="custom-failure-reporter" className="block text-sm text-bambu-gray mb-1">
                  {t('customFailure.modal.reportedBy')}
                </label>
                <input
                  id="custom-failure-reporter"
                  type="text"
                  maxLength={100}
                  className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                  value={reportedBy}
                  onChange={(e) => setReportedBy(e.target.value)}
                />
                <p className="text-xs text-bambu-gray mt-1">{t('customFailure.modal.reportedByHelp')}</p>
              </div>
            </div>
          )}

          {!showSettings && (
            <div className="flex flex-wrap gap-3 mt-6">
              {existing && canWithdraw && (
                <Button variant="danger" onClick={() => withdrawMutation.mutate()} disabled={busy}>
                  {t('customFailure.modal.withdraw')}
                </Button>
              )}
              <Button variant="secondary" onClick={onClose} className="flex-1" disabled={busy}>
                {t('common.cancel')}
              </Button>
              <Button onClick={() => saveMutation.mutate()} className="flex-1" disabled={!print || !reason || busy}>
                {saveMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                {existing ? t('customFailure.modal.update') : t('customFailure.modal.submit')}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
