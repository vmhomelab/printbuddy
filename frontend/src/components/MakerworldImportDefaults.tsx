import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';
import { api } from '../api/client';
import { Card, CardContent, CardHeader } from './Card';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';

/**
 * Defaults applied to new MakerWorld imports (source archive, cover thumbnail).
 * Stored in the app settings; the MakerWorld tab reads them to preset its
 * per-import checkboxes.
 */
export function MakerworldImportDefaults() {
  const { t } = useTranslation();
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const canUpdateSettings = hasPermission('settings:update');

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.getSettings(),
  });
  const archiveDefault = settingsQuery.data?.makerworld_archive_details_default ?? false;
  const coverDefault = settingsQuery.data?.makerworld_cover_thumbnail_default ?? false;

  const mutation = useMutation({
    mutationFn: (defaults: {
      makerworld_archive_details_default: boolean;
      makerworld_cover_thumbnail_default: boolean;
    }) => api.updateSettings(defaults),
    onSuccess: (settings) => {
      queryClient.setQueryData(['settings'], settings);
      showToast(t('makerworld.importDefaultsSaved'), 'success');
    },
    onError: (err: Error) => showToast(err.message || t('makerworld.importDefaultsSaveFailed'), 'error'),
  });

  const update = (archiveByDefault: boolean, coverByDefault: boolean) => {
    if (!canUpdateSettings) return;
    // A cover thumbnail comes from the archived details, so it implies archiving.
    mutation.mutate({
      makerworld_archive_details_default: archiveByDefault || coverByDefault,
      makerworld_cover_thumbnail_default: coverByDefault,
    });
  };

  const disabled = !canUpdateSettings || mutation.isPending || settingsQuery.isLoading;

  return (
    <Card id="card-makerworld-defaults">
      <CardHeader>
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Globe className="w-5 h-5 text-bambu-green" />
          {t('modelImport.makerworldDefaultsTitle')}
        </h2>
      </CardHeader>
      <CardContent>
        <div className="space-y-3 text-sm">
          <p className="text-sm text-bambu-gray">{t('makerworld.importDefaultsDescription')}</p>
          <label className="flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              aria-label={t('makerworld.archiveDetailsDefaultControl')}
              checked={archiveDefault}
              onChange={(event) => update(event.target.checked, event.target.checked ? coverDefault : false)}
              disabled={disabled}
              className="mt-0.5 h-4 w-4 rounded border-gray-400 text-bambu-green focus:ring-bambu-green"
            />
            <span>
              <span className="block font-medium text-white">{t('makerworld.archiveDetailsByDefault')}</span>
              <span className="block text-xs text-bambu-gray">
                {t('makerworld.archiveDetailsByDefaultDescription')}
              </span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              aria-label={t('makerworld.coverThumbnailDefaultControl')}
              checked={coverDefault}
              onChange={(event) => update(archiveDefault, event.target.checked)}
              disabled={disabled}
              className="mt-0.5 h-4 w-4 rounded border-gray-400 text-bambu-green focus:ring-bambu-green"
            />
            <span>
              <span className="block font-medium text-white">{t('makerworld.useCoverAsThumbnailByDefault')}</span>
              <span className="block text-xs text-bambu-gray">
                {t('makerworld.useCoverAsThumbnailByDefaultDescription')}
              </span>
            </span>
          </label>
        </div>
      </CardContent>
    </Card>
  );
}
