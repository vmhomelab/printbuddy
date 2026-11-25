import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, Eye, EyeOff, ImageUp, Loader2, Pencil, Plus, RotateCcw, Trash2, X } from 'lucide-react';
import { api } from '../api/client';
import type { CustomFailureReason } from '../api/client';
import { Button } from './Button';
import { ConfirmModal } from './ConfirmModal';
import { FailureReasonIcon } from './FailureReasonIcon';
import { FAILURE_REASON_ICONS } from '../utils/failureReasonIcons';
import { useToast } from '../contexts/ToastContext';
import { customFailureReasonSubtitle, customFailureReasonTitle } from '../utils/customFailure';

export const MAX_FAILURE_REASONS = 100;
const ICON_UPLOAD_MAX_BYTES = 10 * 1024 * 1024;

interface FailureReasonSettingsProps {
  /** All reasons, hidden ones included, in display order. */
  reasons: CustomFailureReason[];
}

/**
 * The cog view of "Report failed print": hide/restore default reasons, add, edit,
 * re-order and delete custom reasons, pick a built-in icon or upload an image.
 * Modelled on the maintenance types.
 */
export function FailureReasonSettings({ reasons }: FailureReasonSettingsProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [editing, setEditing] = useState<CustomFailureReason | 'new' | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<CustomFailureReason | null>(null);

  const visible = reasons.filter((r) => !r.is_hidden);
  const hidden = reasons.filter((r) => r.is_hidden);
  const hiddenDefaults = hidden.filter((r) => r.is_system).length;

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['customFailureReasons'] });
    queryClient.invalidateQueries({ queryKey: ['customFailureStats'] });
  };
  const onError = (error: Error) => showToast(error.message || t('customFailure.settings.saveFailed'), 'error');

  const removeMutation = useMutation({
    mutationFn: (reason: CustomFailureReason) => api.deleteCustomFailureReason(reason.id),
    onSuccess: (result) => {
      refresh();
      setConfirmDelete(null);
      showToast(
        t(result.status === 'deleted' ? 'customFailure.settings.deleted' : 'customFailure.settings.hidden'),
        'success'
      );
    },
    onError,
  });
  const showMutation = useMutation({
    mutationFn: (reason: CustomFailureReason) => api.updateCustomFailureReason(reason.id, { is_hidden: false }),
    onSuccess: refresh,
    onError,
  });
  const restoreMutation = useMutation({
    mutationFn: api.restoreDefaultCustomFailureReasons,
    onSuccess: (result) => {
      refresh();
      showToast(t('customFailure.settings.defaultsRestored', { count: result.restored }), 'success');
    },
    onError,
  });
  const orderMutation = useMutation({
    mutationFn: (ids: number[]) => api.reorderCustomFailureReasons(ids),
    onSuccess: refresh,
    onError,
  });

  const move = (index: number, delta: number) => {
    const ids = visible.map((r) => r.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    orderMutation.mutate([...ids, ...hidden.map((r) => r.id)]);
  };

  if (editing) {
    return (
      <ReasonEditor
        reason={editing === 'new' ? null : editing}
        onDone={() => {
          refresh();
          setEditing(null);
        }}
        onCancel={() => setEditing(null)}
      />
    );
  }

  const limitReached = reasons.length >= MAX_FAILURE_REASONS;
  const busy = removeMutation.isPending || orderMutation.isPending || showMutation.isPending;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          onClick={() => setEditing('new')}
          disabled={limitReached}
          title={limitReached ? t('customFailure.settings.limitReached', { max: MAX_FAILURE_REASONS }) : undefined}
        >
          <Plus className="w-4 h-4" />
          {t('customFailure.settings.add')}
        </Button>
        {hiddenDefaults > 0 && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => restoreMutation.mutate()}
            disabled={restoreMutation.isPending}
          >
            <RotateCcw className="w-4 h-4" />
            {t('customFailure.settings.restoreDefaults')}
          </Button>
        )}
        <span className="ml-auto text-xs text-bambu-gray">
          {t('customFailure.settings.count', { count: reasons.length, max: MAX_FAILURE_REASONS })}
        </span>
      </div>

      <ul className="divide-y divide-bambu-dark-tertiary/60 rounded-lg border border-bambu-dark-tertiary">
        {visible.map((reason, index) => (
          <li key={reason.id} className="flex items-center gap-3 px-3 py-2">
            <FailureReasonIcon reason={reason} className="w-7 h-7 text-bambu-green flex-shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-white truncate">
                {customFailureReasonTitle(t, reason.code, reason)}
                {reason.is_system && (
                  <span className="ml-2 text-[10px] font-normal uppercase tracking-wide text-bambu-gray">
                    {t('customFailure.settings.defaultBadge')}
                  </span>
                )}
              </div>
              <div className="text-xs text-bambu-gray truncate">
                {customFailureReasonSubtitle(t, reason.code, reason)}
              </div>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              <IconButton label={t('customFailure.settings.moveUp')} onClick={() => move(index, -1)} disabled={busy || index === 0}>
                <ArrowUp className="w-4 h-4" />
              </IconButton>
              <IconButton
                label={t('customFailure.settings.moveDown')}
                onClick={() => move(index, 1)}
                disabled={busy || index === visible.length - 1}
              >
                <ArrowDown className="w-4 h-4" />
              </IconButton>
              <IconButton label={t('customFailure.settings.edit')} onClick={() => setEditing(reason)} disabled={busy}>
                <Pencil className="w-4 h-4" />
              </IconButton>
              {reason.is_system ? (
                <IconButton label={t('customFailure.settings.hide')} onClick={() => removeMutation.mutate(reason)} disabled={busy}>
                  <EyeOff className="w-4 h-4" />
                </IconButton>
              ) : (
                <IconButton label={t('customFailure.settings.delete')} onClick={() => setConfirmDelete(reason)} disabled={busy}>
                  <Trash2 className="w-4 h-4" />
                </IconButton>
              )}
            </div>
          </li>
        ))}
      </ul>

      {hidden.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-bambu-gray mb-1">{t('customFailure.settings.hiddenSection')}</h4>
          <p className="text-xs text-bambu-gray mb-2">{t('customFailure.settings.hiddenHelp')}</p>
          <ul className="divide-y divide-bambu-dark-tertiary/60 rounded-lg border border-bambu-dark-tertiary opacity-70">
            {hidden.map((reason) => (
              <li key={reason.id} className="flex items-center gap-3 px-3 py-2">
                <FailureReasonIcon reason={reason} className="w-6 h-6 text-bambu-gray flex-shrink-0" />
                <span className="min-w-0 flex-1 text-sm text-white truncate">
                  {customFailureReasonTitle(t, reason.code, reason)}
                </span>
                <Button size="sm" variant="secondary" onClick={() => showMutation.mutate(reason)} disabled={busy}>
                  <Eye className="w-4 h-4" />
                  {t('customFailure.settings.show')}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {confirmDelete && (
        <ConfirmModal
          title={t('customFailure.settings.delete')}
          message={t('customFailure.settings.deleteConfirm', {
            title: customFailureReasonTitle(t, confirmDelete.code, confirmDelete),
          })}
          confirmText={t('customFailure.settings.delete')}
          variant="danger"
          overlayZIndex="z-[60]"
          isLoading={removeMutation.isPending}
          onConfirm={() => removeMutation.mutate(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className="p-1.5 rounded text-bambu-gray hover:text-white hover:bg-bambu-dark disabled:opacity-30 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}

/** Add or edit one reason: title, subtitle, built-in icon or an own image. */
function ReasonEditor({
  reason,
  onDone,
  onCancel,
}: {
  reason: CustomFailureReason | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const isDefault = !!reason?.is_system;
  const [title, setTitle] = useState(reason?.title ?? '');
  const [subtitle, setSubtitle] = useState(reason?.subtitle ?? '');
  const [icon, setIcon] = useState(reason?.icon ?? 'TriangleAlert');
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [removeImage, setRemoveImage] = useState(false);

  const pendingPreview = useMemo(() => (pendingFile ? URL.createObjectURL(pendingFile) : null), [pendingFile]);
  useEffect(() => () => {
    if (pendingPreview) URL.revokeObjectURL(pendingPreview);
  }, [pendingPreview]);

  const hasStoredImage = !!reason?.custom_icon_filename && !removeImage;
  const showsImage = !!pendingFile || hasStoredImage;

  const saveMutation = useMutation({
    mutationFn: async () => {
      const text = { title: title.trim() || null, subtitle: subtitle.trim() || null };
      // Only send the icon when it changed, so a default reason keeps following the built-in default icon.
      let saved = reason
        ? await api.updateCustomFailureReason(reason.id, icon !== reason.icon ? { ...text, icon } : text)
        : await api.createCustomFailureReason({ ...text, title: title.trim(), icon });
      if (pendingFile) saved = await api.uploadCustomFailureReasonIcon(saved.id, pendingFile);
      else if (removeImage && reason?.custom_icon_filename) saved = await api.deleteCustomFailureReasonIcon(saved.id);
      return saved;
    },
    onSuccess: () => {
      showToast(t('customFailure.settings.saved'), 'success');
      onDone();
    },
    onError: (error: Error) => showToast(error.message || t('customFailure.settings.saveFailed'), 'error'),
  });

  const pickFile = (file: File | undefined) => {
    if (!file) return;
    if (file.size > ICON_UPLOAD_MAX_BYTES) {
      showToast(t('customFailure.settings.iconHelp'), 'error');
      return;
    }
    setPendingFile(file);
    setRemoveImage(false);
  };

  const pickBuiltIn = (name: string) => {
    setIcon(name);
    // Choosing a built-in icon replaces an own image.
    setPendingFile(null);
    if (reason?.custom_icon_filename) setRemoveImage(true);
  };

  const canSave = (isDefault || title.trim().length > 0) && !saveMutation.isPending;
  const defaultTitle = reason ? customFailureReasonTitle(t, reason.code) : '';
  const defaultSubtitle = reason ? customFailureReasonSubtitle(t, reason.code) : '';

  return (
    <div className="space-y-4">
      <h4 className="text-base font-semibold text-white">
        {reason ? t('customFailure.settings.editTitle') : t('customFailure.settings.newTitle')}
      </h4>

      <div>
        <label htmlFor="reason-title" className="block text-sm text-bambu-gray mb-1">
          {t('customFailure.settings.fieldTitle')}
        </label>
        <input
          id="reason-title"
          type="text"
          maxLength={100}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={isDefault ? defaultTitle : t('customFailure.settings.fieldTitlePlaceholder')}
          className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
        />
      </div>
      <div>
        <label htmlFor="reason-subtitle" className="block text-sm text-bambu-gray mb-1">
          {t('customFailure.settings.fieldSubtitle')}
        </label>
        <input
          id="reason-subtitle"
          type="text"
          maxLength={300}
          value={subtitle}
          onChange={(e) => setSubtitle(e.target.value)}
          placeholder={isDefault ? defaultSubtitle : t('customFailure.settings.fieldSubtitlePlaceholder')}
          className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
        />
        {isDefault && <p className="text-xs text-bambu-gray mt-1">{t('customFailure.settings.defaultTextHelp')}</p>}
      </div>

      <div>
        <div className="block text-sm text-bambu-gray mb-1">{t('customFailure.settings.icon')}</div>
        <div className="flex flex-wrap items-center gap-3 mb-2">
          <div className="w-16 h-16 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark flex items-center justify-center">
            {pendingPreview ? (
              <img src={pendingPreview} alt="" className="w-12 h-12 object-contain" />
            ) : (
              <FailureReasonIcon
                reason={{ id: reason?.id ?? 0, icon, custom_icon_filename: hasStoredImage ? reason!.custom_icon_filename : null }}
                className="w-10 h-10 text-bambu-green"
              />
            )}
          </div>
          <label className="inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg bg-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary/80 cursor-pointer">
            <ImageUp className="w-4 h-4" />
            {showsImage ? t('customFailure.settings.replaceIcon') : t('customFailure.settings.uploadIcon')}
            <input
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              className="hidden"
              data-testid="reason-icon-upload"
              onChange={(e) => {
                pickFile(e.target.files?.[0]);
                e.target.value = '';
              }}
            />
          </label>
          {showsImage && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setPendingFile(null);
                if (reason?.custom_icon_filename) setRemoveImage(true);
              }}
            >
              <X className="w-4 h-4" />
              {t('customFailure.settings.removeIcon')}
            </Button>
          )}
        </div>
        <p className="text-xs text-bambu-gray mb-2">
          {t('customFailure.settings.iconHelp')}
          {pendingFile && <> · {t('customFailure.settings.iconPending')}</>}
        </p>
        <div className="grid grid-cols-7 sm:grid-cols-10 gap-1">
          {Object.entries(FAILURE_REASON_ICONS).map(([name, Icon]) => {
            const selected = !showsImage && icon === name;
            return (
              <button
                key={name}
                type="button"
                title={name}
                aria-label={name}
                aria-pressed={selected}
                onClick={() => pickBuiltIn(name)}
                className={`p-2 rounded-lg flex items-center justify-center border ${
                  selected
                    ? 'border-bambu-green bg-bambu-green/20 text-bambu-green'
                    : 'border-transparent text-bambu-gray hover:text-white hover:bg-bambu-dark'
                }`}
              >
                <Icon className="w-5 h-5" />
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex gap-3">
        <Button variant="secondary" className="flex-1" onClick={onCancel} disabled={saveMutation.isPending}>
          {t('common.cancel')}
        </Button>
        <Button className="flex-1" onClick={() => saveMutation.mutate()} disabled={!canSave}>
          {saveMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          {t('customFailure.settings.save')}
        </Button>
      </div>
    </div>
  );
}
