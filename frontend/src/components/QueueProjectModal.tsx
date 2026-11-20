import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { X, FolderKanban, Loader2, XCircle, Search, Check } from 'lucide-react';
import { api } from '../api/client';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

interface QueueProjectModalProps {
  itemIds: number[];
  /** Project the items are currently linked to (highlighted in the list). */
  currentProjectId?: number | null;
  onClose: () => void;
}

/**
 * Link print-queue items to a project — works for every item type, including
 * archive-only uploads from a virtual printer in queue mode. Optionally adds
 * the items to the project's job plan (archive files are copied into the File
 * Manager by the backend for that).
 */
export function QueueProjectModal({ itemIds, currentProjectId, onClose }: QueueProjectModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [query, setQuery] = useState('');
  const [addToPlan, setAddToPlan] = useState(false);

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.getProjects(),
  });

  const sortedProjects = useMemo(
    () => (projects ? [...projects].sort((a, b) => a.name.localeCompare(b.name)) : undefined),
    [projects],
  );
  const trimmed = query.trim().toLowerCase();
  const visibleProjects = trimmed
    ? sortedProjects?.filter((p) => p.name.toLowerCase().includes(trimmed))
    : sortedProjects;
  const showSearch = (sortedProjects?.length ?? 0) > 5;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const linkMutation = useMutation({
    mutationFn: (projectId: number | null) =>
      api.linkQueueItemsToProject({
        item_ids: itemIds,
        project_id: projectId,
        add_to_plan: projectId !== null && addToPlan,
      }),
    onSuccess: (result, projectId) => {
      for (const key of [
        'queue',
        'queueHistory',
        'archives',
        'projects',
        'project',
        'project-archives',
        'project-plan',
        'project-plan-summary',
        'project-costs',
        'project-files',
        'library-files',
        'library-files-all-for-plan',
      ]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
      if (projectId === null) {
        showToast(t('queue.projectLink.unlinked', { count: result.updated_count }));
      } else {
        const name = projects?.find((p) => p.id === projectId)?.name ?? '';
        showToast(t('queue.projectLink.linked', { count: result.updated_count, name }));
        if (addToPlan) {
          showToast(
            t('queue.projectLink.planResult', {
              created: result.plan_items_created,
              files: result.library_files_created,
            }),
          );
        }
      }
      onClose();
    },
    onError: () => showToast(t('queue.projectLink.failed'), 'error'),
  });

  const isPending = linkMutation.isPending;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <Card className="w-full max-w-md max-h-[80vh] flex flex-col" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
        <CardContent className="p-0 flex flex-col min-h-0">
          <div className="flex items-center justify-between p-4 border-b border-bambu-dark-tertiary shrink-0">
            <div className="flex items-center gap-2">
              <FolderKanban className="w-5 h-5 text-bambu-green" />
              <h2 className="text-xl font-semibold text-white">{t('queue.projectLink.title')}</h2>
            </div>
            <button
              onClick={onClose}
              className="text-bambu-gray hover:text-white transition-colors"
              disabled={isPending}
              aria-label={t('common.close')}
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="p-4 space-y-3 overflow-y-auto min-h-0">
            <p className="text-sm text-bambu-gray">{t('queue.projectLink.description', { count: itemIds.length })}</p>

            <label className="flex items-start gap-3 p-3 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary cursor-pointer">
              <input
                type="checkbox"
                checked={addToPlan}
                onChange={(e) => setAddToPlan(e.target.checked)}
                disabled={isPending}
                className="mt-0.5 accent-bambu-green"
              />
              <span className="min-w-0">
                <span className="block text-sm text-white font-medium">{t('queue.projectLink.addToPlan')}</span>
                <span className="block text-xs text-bambu-gray">{t('queue.projectLink.addToPlanHint')}</span>
              </span>
            </label>

            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-bambu-gray" />
              </div>
            ) : (
              <div className="space-y-2">
                {currentProjectId != null && (
                  <button
                    onClick={() => linkMutation.mutate(null)}
                    disabled={isPending}
                    className="w-full flex items-center gap-3 p-3 rounded-lg bg-bambu-dark hover:bg-bambu-dark-tertiary border border-bambu-dark-tertiary transition-colors text-left disabled:opacity-50"
                  >
                    <div className="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center shrink-0">
                      <XCircle className="w-4 h-4 text-red-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-white font-medium">{t('queue.projectLink.remove')}</p>
                      <p className="text-sm text-bambu-gray truncate">{t('queue.projectLink.removeHint')}</p>
                    </div>
                  </button>
                )}

                {showSearch && (
                  <div className="relative">
                    <Search className="w-4 h-4 text-bambu-gray absolute left-3 top-1/2 -translate-y-1/2" />
                    <input
                      type="text"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder={t('queue.projectLink.search')}
                      className="w-full pl-9 pr-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm focus:outline-none focus:border-bambu-green"
                      autoFocus
                    />
                  </div>
                )}

                {sortedProjects && sortedProjects.length === 0 && (
                  <p className="text-sm text-bambu-gray text-center py-4">{t('queue.projectLink.noProjects')}</p>
                )}

                {visibleProjects?.map((project) => (
                  <button
                    key={project.id}
                    onClick={() => linkMutation.mutate(project.id)}
                    disabled={isPending}
                    className={`w-full flex items-center gap-3 p-3 rounded-lg border transition-colors text-left disabled:opacity-50 ${
                      project.id === currentProjectId
                        ? 'bg-bambu-green/10 border-bambu-green/40'
                        : 'bg-bambu-dark hover:bg-bambu-dark-tertiary border-bambu-dark-tertiary'
                    }`}
                  >
                    <div
                      className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
                      style={{ backgroundColor: `${project.color || '#00ae42'}33` }}
                    >
                      <FolderKanban className="w-4 h-4" style={{ color: project.color || '#00ae42' }} />
                    </div>
                    <p className="text-white font-medium truncate min-w-0 flex-1">{project.name}</p>
                    {project.id === currentProjectId && <Check className="w-4 h-4 text-bambu-green shrink-0" />}
                    {isPending && linkMutation.variables === project.id && (
                      <Loader2 className="w-4 h-4 animate-spin text-bambu-gray shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
