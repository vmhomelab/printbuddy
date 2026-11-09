import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  Boxes,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  FolderOpen,
  Loader2,
  Search,
  X,
} from 'lucide-react';

import {
  api,
  type GyroidVaultImportResponse,
  type GyroidVaultModelQuery,
  type GyroidVaultModelSummary,
  type LibraryFolderTree,
} from '../api/client';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { formatFileSize } from '../utils/file';

const PAGE_SIZE = 24;
const FORMATS = ['stl', '3mf', 'gcode', 'step', 'obj'] as const;
const SORTS: NonNullable<GyroidVaultModelQuery['sort']>[] = ['updated', 'created', 'name', 'prints'];

const selectClass =
  'px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none';

type FlatFolder = { folder: LibraryFolderTree; depth: number };
function flattenFolders(trees: LibraryFolderTree[], depth = 0, out: FlatFolder[] = []): FlatFolder[] {
  for (const tree of trees) {
    out.push({ folder: tree, depth });
    flattenFolders(tree.children ?? [], depth + 1, out);
  }
  return out;
}

function libraryLink(folderId: number | null | undefined): string {
  return folderId ? `/files?folder=${folderId}` : '/files';
}

function Thumbnail({ path, alt, className }: { path: string | null; alt: string; className: string }) {
  const [failed, setFailed] = useState(false);
  if (!path || failed) {
    return (
      <div className={`${className} flex items-center justify-center bg-bambu-dark text-bambu-gray`}>
        <Boxes className="w-8 h-8" />
      </div>
    );
  }
  return (
    <img
      src={api.getGyroidVaultAssetUrl(path)}
      alt={alt}
      className={`${className} object-cover`}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

export function GyroidVaultPage() {
  const { t } = useTranslation();
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const canImport = hasPermission('library:upload');
  const canConfigure = hasPermission('settings:update');

  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [tag, setTag] = useState('');
  const [format, setFormat] = useState('');
  const [sort, setSort] = useState<NonNullable<GyroidVaultModelQuery['sort']>>('updated');
  const [page, setPage] = useState(1);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(() => new Set());
  const [folderId, setFolderId] = useState<number | null>(null);
  const [lastImport, setLastImport] = useState<GyroidVaultImportResponse | null>(null);

  const statusQuery = useQuery({
    queryKey: ['gyroidvault-status'],
    queryFn: api.getGyroidVaultStatus,
    staleTime: 60_000,
  });
  const ready = !!statusQuery.data?.connected;

  const query: GyroidVaultModelQuery = { search, category, tag, format, sort, page, limit: PAGE_SIZE };
  const modelsQuery = useQuery({
    queryKey: ['gyroidvault-models', query],
    queryFn: () => api.getGyroidVaultModels(query),
    enabled: ready,
    placeholderData: (prev) => prev,
  });
  const categoriesQuery = useQuery({
    queryKey: ['gyroidvault-categories'],
    queryFn: api.getGyroidVaultCategories,
    enabled: ready,
    staleTime: 5 * 60_000,
  });
  const tagsQuery = useQuery({
    queryKey: ['gyroidvault-tags'],
    queryFn: api.getGyroidVaultTags,
    enabled: ready,
    staleTime: 5 * 60_000,
  });
  const detailQuery = useQuery({
    queryKey: ['gyroidvault-model', selectedModelId],
    queryFn: () => api.getGyroidVaultModel(selectedModelId as number),
    enabled: ready && selectedModelId !== null,
  });
  const foldersQuery = useQuery({
    queryKey: ['library-folders'],
    queryFn: () => api.getLibraryFolders(),
    enabled: canImport,
  });
  const recentQuery = useQuery({
    queryKey: ['gyroidvault-recent-imports'],
    queryFn: () => api.getGyroidVaultRecentImports(10),
  });

  const detail = detailQuery.data;

  // Preselect every importable file that is not in the library yet.
  useEffect(() => {
    if (!detail) return;
    setSelectedFileIds(
      new Set(detail.files.filter((f) => f.importable && !f.imported_library_file_id).map((f) => f.id)),
    );
    setLastImport(null);
  }, [detail]);

  // Filters change the result set, so go back to the first page.
  useEffect(() => {
    setPage(1);
  }, [search, category, tag, format, sort]);

  const folderOptions = useMemo(
    () =>
      flattenFolders(foldersQuery.data ?? []).filter(
        ({ folder }) => !(folder.is_external && folder.external_readonly),
      ),
    [foldersQuery.data],
  );

  const importMutation = useMutation({
    mutationFn: () =>
      api.importGyroidVaultFiles(selectedModelId as number, Array.from(selectedFileIds), folderId),
    onSuccess: (result) => {
      setLastImport(result);
      queryClient.invalidateQueries({ queryKey: ['gyroidvault-model', selectedModelId] });
      queryClient.invalidateQueries({ queryKey: ['gyroidvault-recent-imports'] });
      queryClient.invalidateQueries({ queryKey: ['library-folders'] });
      queryClient.invalidateQueries({ queryKey: ['library-files'] });
      const failed = result.files.filter((f) => f.error).length;
      const ok = result.files.length - failed;
      if (failed === 0) {
        showToast(t('gyroidvault.importSuccess', { count: ok }), 'success');
      } else {
        showToast(t('gyroidvault.importPartial', { ok, failed }), ok > 0 ? 'warning' : 'error');
      }
    },
    onError: (err: Error) => showToast(err.message || t('gyroidvault.errors.importFailed'), 'error'),
  });

  const toggleFile = (id: number) => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const models: GyroidVaultModelSummary[] = modelsQuery.data?.models ?? [];
  const totalPages = modelsQuery.data?.total_pages ?? 0;
  const importErrors = new Map(
    (lastImport?.files ?? []).filter((f) => f.error).map((f) => [f.gyroidvault_file_id, f.error]),
  );

  return (
    <div className="p-4 md:p-8 max-w-screen-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <Boxes className="w-7 h-7 text-bambu-green" />
          {t('gyroidvault.title')}
        </h1>
        <p className="text-bambu-gray mt-1">{t('gyroidvault.description')}</p>
      </div>

      {statusQuery.isLoading && (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 text-bambu-green animate-spin" />
        </div>
      )}

      {statusQuery.data && !ready && (
        <Card className="border-amber-700 bg-amber-900/20">
          <CardContent>
            <div className="flex items-start gap-3 py-2 text-sm">
              <AlertCircle className="w-5 h-5 text-amber-400 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-amber-100">
                  {!statusQuery.data.enabled || !statusQuery.data.configured
                    ? t('gyroidvault.notConfiguredTitle')
                    : t('gyroidvault.notConnectedTitle')}
                </p>
                <p className="text-amber-200 mt-1">
                  {statusQuery.data.error ?? t('gyroidvault.notConfiguredBody')}{' '}
                  {canConfigure && (
                    <Link to="/settings?tab=network" className="underline">
                      {t('gyroidvault.openSettings')}
                    </Link>
                  )}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {ready && (
        <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
          <div className="space-y-4 min-w-0">
            <Card>
              <CardContent>
                <form
                  className="flex flex-wrap gap-2 py-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    setSearch(searchInput.trim());
                  }}
                >
                  <div className="flex flex-1 min-w-[14rem] gap-2">
                    <input
                      type="search"
                      value={searchInput}
                      onChange={(e) => setSearchInput(e.target.value)}
                      placeholder={t('gyroidvault.searchPlaceholder')}
                      className={`${selectClass} flex-1 min-w-0`}
                      aria-label={t('gyroidvault.searchPlaceholder')}
                    />
                    <Button type="submit" variant="primary" aria-label={t('gyroidvault.search')}>
                      <Search className="w-4 h-4" />
                    </Button>
                  </div>
                  <select
                    className={selectClass}
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    aria-label={t('gyroidvault.category')}
                  >
                    <option value="">{t('gyroidvault.allCategories')}</option>
                    {(categoriesQuery.data ?? []).map((c) => (
                      <option key={c.id} value={String(c.id)}>
                        {c.name} ({c.model_count})
                      </option>
                    ))}
                  </select>
                  <select
                    className={selectClass}
                    value={tag}
                    onChange={(e) => setTag(e.target.value)}
                    aria-label={t('gyroidvault.tag')}
                  >
                    <option value="">{t('gyroidvault.allTags')}</option>
                    {(tagsQuery.data ?? []).map((tg) => (
                      <option key={tg.id} value={String(tg.id)}>
                        {tg.name}
                      </option>
                    ))}
                  </select>
                  <select
                    className={selectClass}
                    value={format}
                    onChange={(e) => setFormat(e.target.value)}
                    aria-label={t('gyroidvault.format')}
                  >
                    <option value="">{t('gyroidvault.allFormats')}</option>
                    {FORMATS.map((f) => (
                      <option key={f} value={f}>
                        {f.toUpperCase()}
                      </option>
                    ))}
                  </select>
                  <select
                    className={selectClass}
                    value={sort}
                    onChange={(e) => setSort(e.target.value as typeof sort)}
                    aria-label={t('gyroidvault.sort')}
                  >
                    {SORTS.map((s) => (
                      <option key={s} value={s}>
                        {t(`gyroidvault.sortBy.${s}`)}
                      </option>
                    ))}
                  </select>
                </form>
              </CardContent>
            </Card>

            {modelsQuery.isError && (
              <p className="text-sm text-red-400">{(modelsQuery.error as Error).message}</p>
            )}

            {modelsQuery.isLoading ? (
              <div className="flex justify-center py-12">
                <Loader2 className="w-6 h-6 text-bambu-green animate-spin" />
              </div>
            ) : models.length === 0 ? (
              <p className="text-bambu-gray text-center py-12">{t('gyroidvault.noModels')}</p>
            ) : (
              <div className="grid gap-4 grid-cols-2 sm:grid-cols-3 xl:grid-cols-4">
                {models.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setSelectedModelId(m.id)}
                    className={`text-left rounded-xl overflow-hidden border-2 bg-bambu-dark-secondary transition-colors ${
                      selectedModelId === m.id
                        ? 'border-bambu-green'
                        : 'border-bambu-dark-tertiary hover:border-bambu-gray/50'
                    }`}
                  >
                    <Thumbnail path={m.thumbnail_path} alt={m.name} className="w-full aspect-square" />
                    <div className="p-3 space-y-1">
                      <p className="text-white font-medium truncate" title={m.name}>
                        {m.name}
                      </p>
                      <p className="text-xs text-bambu-gray truncate">
                        {[m.category_name, m.file_types.filter((ft) => ft !== 'document' && ft !== 'image').join(', ')]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-3">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  aria-label={t('gyroidvault.previousPage')}
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <span className="text-sm text-bambu-gray">
                  {t('gyroidvault.pageOf', { page, total: totalPages })}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  aria-label={t('gyroidvault.nextPage')}
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            )}
          </div>

          <aside className="space-y-4 lg:sticky lg:top-4 self-start">
            {selectedModelId === null ? (
              <Card>
                <CardContent>
                  <p className="text-sm text-bambu-gray py-4 text-center">{t('gyroidvault.selectModelHint')}</p>
                </CardContent>
              </Card>
            ) : detailQuery.isLoading || !detail ? (
              <Card>
                <CardContent>
                  {detailQuery.isError ? (
                    <p className="text-sm text-red-400 py-4">{(detailQuery.error as Error).message}</p>
                  ) : (
                    <div className="flex justify-center py-8">
                      <Loader2 className="w-6 h-6 text-bambu-green animate-spin" />
                    </div>
                  )}
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="text-lg font-semibold text-white break-words min-w-0">{detail.name}</h2>
                    <button
                      type="button"
                      onClick={() => setSelectedModelId(null)}
                      className="text-bambu-gray hover:text-white"
                      aria-label={t('common.close', 'Close')}
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Thumbnail path={detail.thumbnail_path} alt={detail.name} className="w-full aspect-video rounded-lg" />
                  {detail.description && (
                    <p className="text-sm text-bambu-gray whitespace-pre-line line-clamp-6">{detail.description}</p>
                  )}
                  {detail.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {detail.tags.map((tg) => (
                        <span key={tg.id} className="text-xs px-2 py-0.5 rounded-full bg-bambu-dark text-bambu-gray">
                          {tg.name}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-3 text-sm">
                    <a
                      href={detail.web_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-bambu-green hover:underline"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      {t('gyroidvault.openInGyroidVault')}
                    </a>
                    {detail.source_url && (
                      <a
                        href={detail.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-bambu-gray hover:underline"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        {t('gyroidvault.originalSource')}
                      </a>
                    )}
                  </div>

                  <div>
                    <p className="text-sm font-medium text-white mb-2">{t('gyroidvault.files')}</p>
                    {detail.files.length === 0 ? (
                      <p className="text-sm text-bambu-gray">{t('gyroidvault.noFiles')}</p>
                    ) : (
                      <ul className="space-y-1">
                        {detail.files.map((f) => {
                          const imported = f.imported_library_file_id !== null;
                          const error = importErrors.get(f.id);
                          return (
                            <li key={f.id} className="flex items-center gap-2 text-sm">
                              <input
                                type="checkbox"
                                checked={selectedFileIds.has(f.id)}
                                disabled={!f.importable || imported || !canImport}
                                onChange={() => toggleFile(f.id)}
                                aria-label={f.filename}
                                className="accent-bambu-green"
                              />
                              <span
                                className={`flex-1 min-w-0 truncate ${f.importable ? 'text-white' : 'text-bambu-gray'}`}
                                title={f.filename}
                              >
                                {f.filename}
                              </span>
                              <span className="text-xs text-bambu-gray shrink-0">{formatFileSize(f.file_size)}</span>
                              {imported && (
                                <span className="shrink-0 text-bambu-green" title={t('gyroidvault.inLibrary')}>
                                  <Check className="w-4 h-4" />
                                </span>
                              )}
                              {error && (
                                <span className="shrink-0 text-red-400" title={error}>
                                  <AlertCircle className="w-4 h-4" />
                                </span>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>

                  {canImport && (
                    <div className="space-y-2">
                      <label className="block text-sm text-white" htmlFor="gyroidvault-folder">
                        {t('gyroidvault.targetFolder')}
                      </label>
                      <select
                        id="gyroidvault-folder"
                        className={`${selectClass} w-full`}
                        value={folderId ?? ''}
                        onChange={(e) => setFolderId(e.target.value ? Number(e.target.value) : null)}
                      >
                        <option value="">{t('gyroidvault.folderAuto')}</option>
                        {folderOptions.map(({ folder, depth }) => (
                          <option key={folder.id} value={folder.id}>
                            {`${'— '.repeat(depth)}${folder.name}`}
                          </option>
                        ))}
                      </select>
                      <Button
                        variant="primary"
                        className="w-full"
                        disabled={selectedFileIds.size === 0 || importMutation.isPending}
                        onClick={() => importMutation.mutate()}
                      >
                        {importMutation.isPending ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Download className="w-4 h-4" />
                        )}
                        <span className="ml-2">
                          {t('gyroidvault.importSelected', { count: selectedFileIds.size })}
                        </span>
                      </Button>
                      {lastImport && lastImport.files.some((f) => f.library_file_id) && (
                        <Link
                          to={libraryLink(lastImport.folder_id)}
                          className="flex items-center justify-center gap-1 text-sm text-bambu-green hover:underline"
                        >
                          <FolderOpen className="w-4 h-4" />
                          {t('gyroidvault.viewInLibrary')}
                        </Link>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {(recentQuery.data?.length ?? 0) > 0 && (
              <Card>
                <CardHeader>
                  <h2 className="text-sm font-semibold text-white">{t('gyroidvault.recentImports')}</h2>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {recentQuery.data!.map((item) => (
                      <li key={item.library_file_id} className="flex items-center gap-2 text-sm">
                        <Link
                          to={libraryLink(item.folder_id)}
                          className="flex-1 min-w-0 truncate text-white hover:underline"
                          title={item.filename}
                        >
                          {item.filename}
                        </Link>
                        {item.source_url && (
                          <a
                            href={item.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-bambu-gray hover:text-white shrink-0"
                            title={t('gyroidvault.openInGyroidVault')}
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
