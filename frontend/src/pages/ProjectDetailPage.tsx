import { useState, useMemo } from 'react';
import DOMPurify from 'dompurify';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient, useQueries } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  Edit3,
  Loader2,
  Package,
  Clock,
  CheckCircle,
  XCircle,
  ListTodo,
  Printer,
  ChevronRight,
  FileText,
  Tag,
  Calendar,
  AlertTriangle,
  Save,
  X,
  Trash2,
  Plus,
  History,
  FolderTree,
  Copy,
  Layers,
  ExternalLink,
  ShoppingCart,
  FolderOpen,
  Download,
  Pencil,
  Play,
  CalendarPlus,
  FileBox,
} from 'lucide-react';
import { api } from '../api/client';
import { parseUTCDate, formatDateOnly, formatDateTime, formatDurationFromHours, type TimeFormat } from '../utils/date';
import type { Archive, ProjectUpdate, BOMItem, BOMItemCreate, BOMItemUpdate, LibraryFileListItem, Printer as PrintbuddyPrinter, PrinterStatus, PrintQueueItem } from '../api/client';
import { Card, CardContent } from '../components/Card';
import { Button } from '../components/Button';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';
import { RichTextEditor } from '../components/RichTextEditor';
import { ConfirmModal } from '../components/ConfirmModal';
import { PrintModal } from '../components/PrintModal';

// Project edit modal (reused from ProjectsPage)
import { ProjectModal } from './ProjectsPage';
import { getCurrencySymbol } from '../utils/currency';

// Returns true for sliced (printable) files: .gcode and .gcode.3mf
function isSlicedFilename(filename: string): boolean {
  const lower = filename.toLowerCase();
  return lower.endsWith('.gcode') || lower.endsWith('.gcode.3mf');
}

function formatFilament(grams: number): string {
  if (grams >= 1000) {
    return `${(grams / 1000).toFixed(2)}kg`;
  }
  return `${Math.round(grams)}g`;
}

type TFunction = (key: string, options?: Record<string, unknown>) => string;

function StatusBadge({ status, t }: { status: string; t: TFunction }) {
  const colors = {
    active: 'bg-bambu-green/20 text-bambu-green',
    completed: 'bg-blue-500/20 text-blue-400',
    archived: 'bg-bambu-gray/20 text-bambu-gray',
  };
  const color = colors[status as keyof typeof colors] || colors.active;

  const labels: Record<string, string> = {
    active: t('projectDetail.status.active'),
    completed: t('projectDetail.status.completed'),
    archived: t('projectDetail.status.archived'),
  };

  return (
    <span className={`px-2 py-1 rounded text-sm font-medium ${color}`}>
      {labels[status] || status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
  hint,
  color = 'text-bambu-gray',
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  subValue?: string;
  hint?: string;
  color?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-3" title={hint}>
          <div className={`p-2 rounded-lg bg-bambu-dark ${color}`}>
            <Icon className="w-5 h-5" />
          </div>
          <div>
            <p className="text-sm text-bambu-gray">{label}</p>
            <p className="text-xl font-semibold text-white">{value}</p>
            {subValue && <p className="text-xs text-bambu-gray/70">{subValue}</p>}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ArchiveGrid({ archives, t }: { archives: Archive[]; t: TFunction }) {
  if (archives.length === 0) {
    return (
      <div className="text-center py-8 text-bambu-gray">
        <Package className="w-12 h-12 mx-auto mb-2 opacity-50" />
        <p>{t('projectDetail.noPrints')}</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
      {archives.map((archive) => (
        <Link
          key={archive.id}
          to={`/archives?search=${encodeURIComponent(archive.print_name || '')}`}
          className="group relative aspect-square rounded-lg bg-bambu-dark border border-bambu-dark-tertiary overflow-hidden hover:border-bambu-green transition-colors"
        >
          {archive.thumbnail_path ? (
            <img
              src={api.getArchiveThumbnail(archive.id)}
              alt={archive.print_name || 'Print'}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-bambu-gray">
              <Package className="w-8 h-8" />
            </div>
          )}

          {/* Status overlay */}
          {archive.status === 'failed' && (
            <div className="absolute inset-0 bg-red-500/30 flex items-center justify-center">
              <XCircle className="w-8 h-8 text-white" />
            </div>
          )}
          {archive.status === 'completed' && (
            <div className="absolute top-1 right-1">
              <CheckCircle className="w-4 h-4 text-bambu-green" />
            </div>
          )}

          {/* Name overlay on hover */}
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <p className="text-xs text-white truncate">{archive.print_name || 'Unknown'}</p>
          </div>
        </Link>
      ))}
    </div>
  );
}

function PriorityBadge({ priority, t }: { priority: string; t: TFunction }) {
  const config = {
    low: { color: 'bg-gray-500/20 text-gray-400', label: t('projectDetail.priority.low') },
    normal: { color: 'bg-blue-500/20 text-blue-400', label: t('projectDetail.priority.normal') },
    high: { color: 'bg-orange-500/20 text-orange-400', label: t('projectDetail.priority.high') },
    urgent: { color: 'bg-red-500/20 text-red-400', label: t('projectDetail.priority.urgent') },
  };
  const { color, label } = config[priority as keyof typeof config] || config.normal;

  return (
    <span className={`px-2 py-1 rounded text-xs font-medium flex items-center gap-1 ${color}`}>
      {priority === 'urgent' && <AlertTriangle className="w-3 h-3" />}
      {label}
    </span>
  );
}

function getDueDateStatus(dateString: string | null, t: TFunction): { color: string; label: string } | null {
  if (!dateString) return null;
  const dueDate = parseUTCDate(dateString);
  if (!dueDate) return null;
  const now = new Date();
  const diffDays = Math.ceil((dueDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays < 0) return { color: 'text-red-400', label: t('projectDetail.dueDate.overdue') };
  if (diffDays === 0) return { color: 'text-orange-400', label: t('projectDetail.dueDate.today') };
  if (diffDays <= 3) return { color: 'text-yellow-400', label: t('projectDetail.dueDate.daysLeft', { count: diffDays }) };
  return { color: 'text-bambu-gray', label: t('projectDetail.dueDate.daysLeft', { count: diffDays }) };
}

function normalizeProductionName(value: string | null | undefined): string {
  return (value || '')
    .toLowerCase()
    .replace(/\.(gcode\.3mf|gcode|bgcode|3mf|stl)$/i, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function productionTokens(value: string | null | undefined): string[] {
  return normalizeProductionName(value).split(' ').filter((token) => token.length >= 3 && !['plate', 'part', 'print'].includes(token));
}

function fileMatchesPart(part: BOMItem, filename: string | null | undefined): boolean {
  const file = normalizeProductionName(filename);
  if (!file) return false;
  const partSources = [part.name, part.stl_filename].filter(Boolean) as string[];
  return partSources.some((source) => {
    const normalized = normalizeProductionName(source);
    if (normalized && file.includes(normalized)) return true;
    const tokens = productionTokens(source);
    return tokens.length > 0 && tokens.every((token) => file.includes(token));
  });
}

function formatProductionDuration(seconds: number | null | undefined): string | null {
  if (!seconds || seconds <= 0) return null;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function formatProductionFilament(grams: number | null | undefined): string | null {
  if (grams === null || grams === undefined || Number.isNaN(grams)) return null;
  return formatFilament(grams);
}

interface ProductionFileState {
  label: string;
  detail?: string;
  tone: 'blue' | 'amber' | 'green' | 'red';
}

function productionFileMatches(file: LibraryFileListItem, value: string | null | undefined): boolean {
  if (!value) return false;
  const lower = value.toLowerCase();
  return lower.includes(file.filename.toLowerCase()) || (!!file.print_name && lower.includes(file.print_name.toLowerCase()));
}

function buildProductionFileStates(files: LibraryFileListItem[], queue: PrintQueueItem[], printers: PrintbuddyPrinter[], statuses: Array<PrinterStatus | undefined>): Map<number, ProductionFileState> {
  const states = new Map<number, ProductionFileState>();
  files.forEach((file) => {
    const queueItem = queue.find((item) => item.library_file_id === file.id || productionFileMatches(file, `${item.library_file_name || ''} ${item.archive_name || ''}`));
    const printerIndex = statuses.findIndex((status) => productionFileMatches(file, status?.current_print || status?.gcode_file));
    const liveStatus = printerIndex >= 0 ? statuses[printerIndex] : undefined;
    const livePrinter = printerIndex >= 0 ? printers[printerIndex] : undefined;

    if (liveStatus && livePrinter) {
      const progress = liveStatus.progress === null || liveStatus.progress === undefined ? undefined : `${Math.round(liveStatus.progress)}%`;
      states.set(file.id, { label: `Printing on ${livePrinter.name}`, detail: progress, tone: 'blue' });
      return;
    }

    if (queueItem) {
      if (queueItem.status === 'printing') {
        states.set(file.id, { label: `Printing on ${queueItem.printer_name || 'assigned printer'}`, tone: 'blue' });
        return;
      }
      if (queueItem.status === 'failed' || queueItem.status === 'cancelled' || queueItem.status === 'skipped') {
        states.set(file.id, { label: queueItem.status === 'failed' ? 'Failed' : 'Needs review', detail: queueItem.error_message || undefined, tone: 'red' });
        return;
      }
      if (queueItem.status === 'completed') {
        states.set(file.id, { label: 'Completed', tone: 'green' });
        return;
      }
      states.set(file.id, { label: 'Queued', detail: queueItem.printer_name || queueItem.target_model || undefined, tone: 'amber' });
    }
  });
  return states;
}

function ProductionStateBadge({ state }: { state?: ProductionFileState }) {
  const effective = state || { label: 'Needs staging', tone: 'amber' as const };
  const tones = {
    blue: 'bg-blue-500/15 text-blue-300',
    amber: 'bg-yellow-500/15 text-yellow-300',
    green: 'bg-bambu-green/15 text-bambu-green',
    red: 'bg-red-500/15 text-red-300',
  };
  return (
    <div className="flex flex-col gap-1">
      <span className={`inline-flex w-fit rounded px-2 py-1 text-xs font-semibold ${tones[effective.tone]}`}>{effective.label}</span>
      {effective.detail && <span className="text-xs text-bambu-gray-light">{effective.detail}</span>}
    </div>
  );
}

function ProductionPlan({ bomItems, archives, files, fileStates, onStageFile }: { bomItems: BOMItem[]; archives: Archive[]; files: LibraryFileListItem[]; fileStates: Map<number, ProductionFileState>; onStageFile: (file: LibraryFileListItem) => void }) {
  if (bomItems.length === 0 && archives.length === 0 && files.length === 0) return null;

  const unmatchedArchives = archives.filter((archive) => !bomItems.some((item) => fileMatchesPart(item, archive.print_name || archive.filename)));
  const unmatchedFiles = files.filter((file) => !bomItems.some((item) => fileMatchesPart(item, file.filename)));
  const rows = [
    ...bomItems.map((item) => ({
      id: `bom-${item.id}`,
      name: item.name,
      completed: item.quantity_acquired,
      target: item.quantity_needed,
      archives: archives.filter((archive) => fileMatchesPart(item, archive.print_name || archive.filename)),
      files: files.filter((file) => fileMatchesPart(item, file.filename)),
    })),
    ...unmatchedArchives.map((archive) => ({
      id: `archive-${archive.id}`,
      name: archive.print_name || archive.filename,
      completed: archive.status === 'completed' ? archive.quantity : 0,
      target: archive.quantity,
      archives: [archive],
      files: [] as LibraryFileListItem[],
    })),
    ...unmatchedFiles.map((file) => ({
      id: `file-${file.id}`,
      name: file.print_name || file.filename,
      completed: 0,
      target: 0,
      archives: [] as Archive[],
      files: [file],
    })),
  ];

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <FileBox className="w-5 h-5" />
              Production Plan
            </h2>
            <p className="text-xs text-bambu-gray mt-1">Parts, build plates, files, and current production state.</p>
          </div>
          <Link to="/files" className="text-sm text-bambu-green hover:underline">Add files</Link>
        </div>
        <div className="space-y-3">
          {rows.map((row) => (
            <div key={row.id} className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/60 p-4">
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                <div>
                  <h3 className="font-semibold text-white">{row.name}</h3>
                  <p className="text-sm text-bambu-gray">{row.target > 0 ? `${row.completed} / ${row.target} complete` : 'No quantity target set'}</p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="rounded bg-bambu-dark-tertiary px-2 py-1 text-bambu-gray-light">{row.archives.length} archived plate{row.archives.length === 1 ? '' : 's'}</span>
                  <span className="rounded bg-bambu-dark-tertiary px-2 py-1 text-bambu-gray-light">{row.files.length} project file{row.files.length === 1 ? '' : 's'}</span>
                </div>
              </div>
              <div className="mt-3 overflow-hidden rounded-lg border border-bambu-dark-tertiary">
                <table className="w-full text-sm">
                  <thead className="bg-bambu-dark-tertiary text-xs uppercase text-bambu-gray">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Build plate / file</th>
                      <th className="px-3 py-2 text-left font-medium">State</th>
                      <th className="px-3 py-2 text-left font-medium">Material</th>
                      <th className="px-3 py-2 text-left font-medium">Model</th>
                      <th className="px-3 py-2 text-left font-medium">Plate</th>
                      <th className="px-3 py-2 text-left font-medium">Estimate</th>
                      <th className="px-3 py-2 text-right font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-bambu-dark-tertiary">
                    {row.archives.map((archive) => (
                      <tr key={`archive-${archive.id}`}>
                        <td className="px-3 py-2 text-white">{archive.print_name || archive.filename}</td>
                        <td className="px-3 py-2 text-bambu-green">{archive.status}</td>
                        <td className="px-3 py-2 text-bambu-gray-light">{archive.filament_type || '-'}</td>
                        <td className="px-3 py-2 text-bambu-gray-light">{archive.sliced_for_model || '-'}</td>
                        <td className="px-3 py-2 text-bambu-gray-light">{archive.bed_type || '-'}</td>
                        <td className="px-3 py-2 text-bambu-gray-light">{[formatProductionFilament(archive.filament_used_grams), formatProductionDuration(archive.print_time_seconds)].filter(Boolean).join(' · ') || '-'}</td>
                        <td className="px-3 py-2 text-right text-bambu-gray-light">Archived</td>
                      </tr>
                    ))}
                    {row.files.map((file) => (
                      <tr key={`file-${file.id}`}>
                        <td className="px-3 py-2 text-white">{file.print_name || file.filename}</td>
                        <td className="px-3 py-2"><ProductionStateBadge state={fileStates.get(file.id)} /></td>
                        <td className="px-3 py-2 text-bambu-gray-light">-</td>
                        <td className="px-3 py-2 text-bambu-gray-light">-</td>
                        <td className="px-3 py-2 text-bambu-gray-light">-</td>
                        <td className="px-3 py-2 text-bambu-gray-light">-</td>
                        <td className="px-3 py-2 text-right">
                          {isSlicedFilename(file.filename) ? (
                            <button
                              type="button"
                              onClick={() => onStageFile(file)}
                              className="inline-flex items-center gap-1 rounded bg-blue-500/15 px-2 py-1 text-xs font-semibold text-blue-300 transition hover:bg-blue-500/25 hover:text-white"
                              aria-label={`Stage ${file.print_name || file.filename} to queue`}
                            >
                              <CalendarPlus className="h-3.5 w-3.5" /> Stage to queue
                            </button>
                          ) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

type DispatchState = 'ready' | 'blocked';

interface DispatchSuggestion {
  file: LibraryFileListItem;
  state: DispatchState;
  printer: PrintbuddyPrinter | null;
  reason: string;
}

function isPrinterDispatchReady(status?: PrinterStatus): boolean {
  if (!status || !status.connected) return false;
  if ((status.hms_errors?.length ?? 0) > 0) return false;
  const state = (status.state || '').toLowerCase();
  if (state.includes('error') || state.includes('fail') || state.includes('pause')) return false;
  if (state.includes('print') || state.includes('run') || status.current_print || status.progress !== null) return false;
  return true;
}

function buildDispatchSuggestions(files: LibraryFileListItem[], printers: PrintbuddyPrinter[], statuses: Array<PrinterStatus | undefined>, queue: PrintQueueItem[]): DispatchSuggestion[] {
  const printableFiles = files.filter((file) => isSlicedFilename(file.filename));
  return printableFiles.map((file) => {
    const alreadyQueued = queue.some((item) => {
      if (item.library_file_id === file.id) return true;
      const candidate = `${item.library_file_name || ''} ${item.archive_name || ''}`.toLowerCase();
      return candidate.includes(file.filename.toLowerCase()) || (!!file.print_name && candidate.includes(file.print_name.toLowerCase()));
    });
    if (alreadyQueued) {
      return { file, state: 'blocked', printer: null, reason: 'Already queued for this project or file name.' };
    }

    const readyIndex = printers.findIndex((printer, index) => printer.is_active !== false && isPrinterDispatchReady(statuses[index]));
    if (readyIndex >= 0) {
      return {
        file,
        state: 'ready',
        printer: printers[readyIndex],
        reason: `${printers[readyIndex].name} is an idle printer and can be reviewed for staging.`,
      };
    }

    return { file, state: 'blocked', printer: null, reason: 'No idle printer is currently available for safe staging.' };
  });
}

function DispatchBatchReviewDialog({ suggestions, onClose, onStageFirst }: { suggestions: DispatchSuggestion[]; onClose: () => void; onStageFirst: (suggestion: DispatchSuggestion) => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="batch-dispatch-review-title">
      <div className="w-full max-w-2xl rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="batch-dispatch-review-title" className="text-xl font-bold text-white">Batch Dispatch Review</h2>
            <p className="mt-1 text-sm text-bambu-gray-light">{suggestions.length} job{suggestions.length === 1 ? '' : 's'} selected for staging review.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close batch dispatch review" className="rounded-lg p-2 text-bambu-gray-light hover:bg-bambu-dark hover:text-white"><X className="h-5 w-5" /></button>
        </div>
        <div className="max-h-[50vh] space-y-3 overflow-y-auto">
          {suggestions.map((suggestion) => {
            const fileName = suggestion.file.print_name || suggestion.file.filename;
            return (
              <div key={suggestion.file.id} className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3">
                <div className="font-semibold text-white">{fileName}</div>
                <div className="mt-1 text-sm text-bambu-gray-light">Target: {suggestion.printer?.name || 'No target'}</div>
                <div className="mt-1 text-xs text-bambu-gray">{suggestion.reason}</div>
              </div>
            );
          })}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-bambu-dark-tertiary px-4 py-2 text-sm font-semibold text-bambu-gray-light hover:text-white">Cancel</button>
          <button type="button" onClick={() => suggestions[0] && onStageFirst(suggestions[0])} disabled={suggestions.length === 0} className="rounded-lg bg-blue-500 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">Stage first selected job</button>
        </div>
      </div>
    </div>
  );
}

function DispatchSuggestions({ suggestions, onReview }: { suggestions: DispatchSuggestion[]; onReview: (suggestion: DispatchSuggestion) => void }) {
  const [selectedFileIds, setSelectedFileIds] = useState<number[]>([]);
  const [showBatchReview, setShowBatchReview] = useState(false);
  if (suggestions.length === 0) return null;

  const readySuggestions = suggestions.filter((suggestion) => suggestion.state === 'ready' && suggestion.printer);
  const selectedSuggestions = suggestions.filter((suggestion) => selectedFileIds.includes(suggestion.file.id) && suggestion.state === 'ready' && suggestion.printer);
  const toggleSelected = (fileId: number) => {
    setSelectedFileIds((current) => current.includes(fileId) ? current.filter((id) => id !== fileId) : [...current, fileId]);
  };

  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <Printer className="h-5 w-5" />
              Dispatch Suggestions
            </h2>
            <p className="mt-1 text-xs text-bambu-gray">Review suggested printer targets before staging. Nothing starts automatically.</p>
          </div>
          {readySuggestions.length > 0 && (
            <button
              type="button"
              onClick={() => setShowBatchReview(true)}
              disabled={selectedSuggestions.length === 0}
              className="inline-flex items-center justify-center gap-2 rounded bg-blue-500/15 px-3 py-2 text-sm font-semibold text-blue-300 transition hover:bg-blue-500/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Review selected dispatch jobs"
            >
              <ListTodo className="h-4 w-4" /> Review selected ({selectedSuggestions.length})
            </button>
          )}
        </div>
        <div className="space-y-3">
          {suggestions.map((suggestion) => {
            const fileName = suggestion.file.print_name || suggestion.file.filename;
            const isReady = suggestion.state === 'ready' && suggestion.printer;
            return (
              <div key={suggestion.file.id} className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/60 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div className="flex gap-3">
                    {isReady && (
                      <input
                        type="checkbox"
                        checked={selectedFileIds.includes(suggestion.file.id)}
                        onChange={() => toggleSelected(suggestion.file.id)}
                        aria-label={`Select ${fileName}`}
                        className="mt-1 h-4 w-4 rounded border-bambu-dark-tertiary bg-bambu-dark text-blue-500"
                      />
                    )}
                    <div>
                      <div className="font-semibold text-white">{fileName}</div>
                      <div className="mt-1 text-sm text-bambu-gray-light">{isReady ? `Suggested printer: ${suggestion.printer!.name}` : 'No safe printer target'}</div>
                      <div className="mt-1 text-xs text-bambu-gray">{suggestion.reason}</div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded px-2 py-1 text-xs font-semibold ${isReady ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'}`}>
                      {isReady ? 'Ready to stage' : 'Blocked'}
                    </span>
                    {isReady && (
                      <button
                        type="button"
                        onClick={() => onReview(suggestion)}
                        className="inline-flex items-center gap-1 rounded bg-blue-500/15 px-3 py-1.5 text-xs font-semibold text-blue-300 transition hover:bg-blue-500/25 hover:text-white"
                        aria-label={`Review staging for ${fileName} on ${suggestion.printer!.name}`}
                      >
                        <CalendarPlus className="h-3.5 w-3.5" /> Review staging
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {showBatchReview && <DispatchBatchReviewDialog suggestions={selectedSuggestions} onClose={() => setShowBatchReview(false)} onStageFirst={(suggestion) => { setShowBatchReview(false); onReview(suggestion); }} />}
      </CardContent>
    </Card>
  );
}

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { hasPermission } = useAuth();
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesContent, setNotesContent] = useState('');
  const [printFile, setPrintFile] = useState<LibraryFileListItem | null>(null);
  const [scheduleFile, setScheduleFile] = useState<LibraryFileListItem | null>(null);
  const [schedulePrinterIds, setSchedulePrinterIds] = useState<number[]>([]);

  const projectId = parseInt(id || '0', 10);

  const { data: project, isLoading: projectLoading, error: projectError } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
  });

  const { data: archives, isLoading: archivesLoading } = useQuery({
    queryKey: ['project-archives', projectId],
    queryFn: () => api.getProjectArchives(projectId),
    enabled: projectId > 0,
  });

  const { data: bomItems, isLoading: bomLoading } = useQuery({
    queryKey: ['project-bom', projectId],
    queryFn: () => api.getProjectBOM(projectId),
    enabled: projectId > 0,
  });

  const { data: timeline, isLoading: timelineLoading } = useQuery({
    queryKey: ['project-timeline', projectId],
    queryFn: () => api.getProjectTimeline(projectId, 20),
    enabled: projectId > 0,
  });

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  });

  const { data: linkedFolders } = useQuery({
    queryKey: ['project-folders', projectId],
    queryFn: () => api.getLibraryFoldersByProject(projectId),
    enabled: projectId > 0,
  });

  // Single bulk query — replaces the previous N+1 useQueries pattern
  const { data: allProjectFiles, isLoading: projectFilesLoading } = useQuery({
    queryKey: ['project-files', projectId],
    queryFn: () => api.getLibraryFiles(null, false, projectId),
    enabled: projectId > 0,
  });

  const { data: printers = [] } = useQuery({
    queryKey: ['printers', 'project-dispatch'],
    queryFn: api.getPrinters,
    enabled: projectId > 0,
  });

  const { data: queue = [] } = useQuery({
    queryKey: ['queue', 'project-dispatch', projectId],
    queryFn: () => api.getQueue(),
    enabled: projectId > 0,
  });

  const printerStatusQueries = useQueries({
    queries: printers.map((printer) => ({
      queryKey: ['printerStatus', printer.id, 'project-dispatch'],
      queryFn: () => api.getPrinterStatus(printer.id),
      enabled: projectId > 0 && printer.is_active !== false,
    })),
  });

  const printerStatuses = printerStatusQueries.map((query) => query.data);
  const productionFileStates = useMemo(() => buildProductionFileStates(
    allProjectFiles || [],
    queue as PrintQueueItem[],
    printers,
    printerStatuses,
  ), [allProjectFiles, queue, printers, printerStatuses]);

  const dispatchSuggestions = useMemo(() => buildDispatchSuggestions(
    allProjectFiles || [],
    printers,
    printerStatuses,
    queue as PrintQueueItem[],
  ), [allProjectFiles, printers, printerStatuses, queue]);

  // Group files by folder_id for the section-based render
  const filesByFolder = useMemo(() => {
    const map = new Map<number, LibraryFileListItem[]>();
    for (const file of allProjectFiles ?? []) {
      if (file.folder_id != null) {
        const arr = map.get(file.folder_id) ?? [];
        arr.push(file);
        map.set(file.folder_id, arr);
      }
    }
    return map;
  }, [allProjectFiles]);

  const currency = getCurrencySymbol(settings?.currency || 'USD');
  const timeFormat: TimeFormat = settings?.time_format || 'system';

  const updateMutation = useMutation({
    mutationFn: (data: ProjectUpdate) => api.updateProject(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setShowEditModal(false);
      setEditingNotes(false);
      showToast(t('projectDetail.toast.projectUpdated'), 'success');
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
    },
  });

  const handleStartEditNotes = () => {
    setNotesContent(project?.notes || '');
    setEditingNotes(true);
  };

  const handleSaveNotes = () => {
    updateMutation.mutate({ notes: notesContent });
  };

  const handleCancelNotes = () => {
    setEditingNotes(false);
    setNotesContent('');
  };

  // BOM handlers
  const [newBomName, setNewBomName] = useState('');
  const [newBomQty, setNewBomQty] = useState(1);
  const [newBomPrice, setNewBomPrice] = useState('');
  const [newBomUrl, setNewBomUrl] = useState('');
  const [newBomRemarks, setNewBomRemarks] = useState('');
  const [showBomForm, setShowBomForm] = useState(false);
  const [hideBomCompleted, setHideBomCompleted] = useState(false);
  const [editingBomItem, setEditingBomItem] = useState<BOMItem | null>(null);
  const [editBomName, setEditBomName] = useState('');
  const [editBomQty, setEditBomQty] = useState(1);
  const [editBomPrice, setEditBomPrice] = useState('');
  const [editBomUrl, setEditBomUrl] = useState('');
  const [editBomRemarks, setEditBomRemarks] = useState('');

  // Confirm modal state
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
  }>({ isOpen: false, title: '', message: '', onConfirm: () => {} });

  const createBomMutation = useMutation({
    mutationFn: (data: BOMItemCreate) => api.createBOMItem(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-bom', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      setNewBomName('');
      setNewBomQty(1);
      setNewBomPrice('');
      setNewBomUrl('');
      setNewBomRemarks('');
      setShowBomForm(false);
      showToast(t('projectDetail.toast.partAdded'), 'success');
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const updateBomMutation = useMutation({
    mutationFn: ({ itemId, data }: { itemId: number; data: BOMItemUpdate }) =>
      api.updateBOMItem(projectId, itemId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-bom', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      setEditingBomItem(null);
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const deleteBomMutation = useMutation({
    mutationFn: (itemId: number) => api.deleteBOMItem(projectId, itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-bom', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      showToast(t('projectDetail.toast.partRemoved'), 'success');
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const handleAddBomItem = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newBomName.trim()) return;
    createBomMutation.mutate({
      name: newBomName.trim(),
      quantity_needed: newBomQty,
      unit_price: newBomPrice ? parseFloat(newBomPrice) : undefined,
      sourcing_url: newBomUrl.trim() || undefined,
      remarks: newBomRemarks.trim() || undefined,
    });
  };

  const handleToggleAcquired = (item: BOMItem) => {
    const newQty = item.is_complete ? 0 : item.quantity_needed;
    updateBomMutation.mutate({
      itemId: item.id,
      data: { quantity_acquired: newQty },
    });
  };

  const handleDeleteBomItem = (itemId: number, itemName: string) => {
    setConfirmModal({
      isOpen: true,
      title: t('projectDetail.bom.deletePart'),
      message: t('projectDetail.bom.deleteConfirm', { name: itemName }),
      onConfirm: () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
        deleteBomMutation.mutate(itemId);
      },
    });
  };

  const handleEditBomItem = (item: BOMItem) => {
    setEditingBomItem(item);
    setEditBomName(item.name);
    setEditBomQty(item.quantity_needed);
    setEditBomPrice(item.unit_price?.toString() || '');
    setEditBomUrl(item.sourcing_url || '');
    setEditBomRemarks(item.remarks || '');
  };

  const handleSaveBomEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingBomItem || !editBomName.trim()) return;
    updateBomMutation.mutate({
      itemId: editingBomItem.id,
      data: {
        name: editBomName.trim(),
        quantity_needed: editBomQty,
        unit_price: editBomPrice ? parseFloat(editBomPrice) : undefined,
        sourcing_url: editBomUrl.trim() || undefined,
        remarks: editBomRemarks.trim() || undefined,
      },
    });
  };

  const handleCancelBomEdit = () => {
    setEditingBomItem(null);
  };

  const handleExportProject = async () => {
    try {
      const { blob, filename } = await api.exportProjectZip(Number(projectId));
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || `${project?.name || 'project'}_${new Date().toISOString().split('T')[0]}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(t('projectDetail.toast.projectExported'), 'success');
    } catch (error) {
      showToast((error as Error).message, 'error');
    }
  };

  // Template handlers
  const createTemplateMutation = useMutation({
    mutationFn: () => api.createTemplateFromProject(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      showToast(t('projectDetail.toast.templateCreated'), 'success');
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const formatTimelineDate = (timestamp: string) => {
    return formatDateTime(timestamp, timeFormat, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="w-8 h-8 animate-spin text-bambu-green" />
      </div>
    );
  }

  if (projectError || !project) {
    return (
      <div className="text-center py-24">
        <p className="text-bambu-gray">
          {projectError ? `${t('common.error')}: ${(projectError as Error).message}` : t('projectDetail.notFound')}
        </p>
        <Button variant="secondary" className="mt-4" onClick={() => navigate('/projects')}>
          {t('projectDetail.backToProjects')}
        </Button>
      </div>
    );
  }

  const stats = project.stats;
  // Plates progress: total_archives / target_count
  const platesProgressPercent = stats?.progress_percent ?? 0;
  // Parts progress: completed_prints / target_parts_count
  const partsProgressPercent = stats?.parts_progress_percent ?? 0;

  return (
    <div className="p-4 md:p-8 space-y-8">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-bambu-gray">
        <Link to="/projects" className="hover:text-white transition-colors">
          {t('nav.projects')}
        </Link>
        <ChevronRight className="w-4 h-4" />
        <span className="text-white">{project.name}</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/projects')}
            className="p-2 rounded-lg bg-bambu-card hover:bg-bambu-dark-tertiary transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-bambu-gray" />
          </button>
          <div className="flex items-center gap-3">
            <div
              className="w-4 h-4 rounded-full shrink-0"
              style={{ backgroundColor: project.color || '#6b7280' }}
            />
            <div>
              <h1 className="text-2xl font-bold text-white">{project.name}</h1>
              {project.description && (
                <p className="text-bambu-gray mt-1">{project.description}</p>
              )}
            </div>
          </div>
          <StatusBadge status={project.status} t={t} />
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={handleExportProject}
            disabled={!hasPermission('projects:read')}
            title={!hasPermission('projects:read') ? t('projectDetail.noExportPermission') : t('projectDetail.exportProject')}
          >
            <Download className="w-4 h-4 mr-2" />
            {t('projectDetail.export')}
          </Button>
          <Button
            onClick={() => setShowEditModal(true)}
            disabled={!hasPermission('projects:update')}
            title={!hasPermission('projects:update') ? t('projectDetail.noEditPermission') : undefined}
          >
            <Edit3 className="w-4 h-4 mr-2" />
            {t('common.edit')}
          </Button>
        </div>
      </div>

      {/* Progress bars (if targets set) */}
      {(project.target_count || project.target_parts_count) && (
        <Card>
          <CardContent className="p-4 space-y-4">
            {/* Plates progress */}
            {project.target_count && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-bambu-gray">{t('projectDetail.progress.platesProgress')}</span>
                  <span className="text-sm font-medium text-white">
                    {stats?.total_archives || 0} / {project.target_count} {t('projectDetail.progress.printJobs')}
                  </span>
                </div>
                <div className="h-3 bg-bambu-dark rounded-full overflow-hidden">
                  <div
                    className="h-full transition-all duration-500"
                    style={{
                      width: `${Math.min(platesProgressPercent, 100)}%`,
                      backgroundColor: platesProgressPercent >= 100 ? '#22c55e' : project.color || '#6b7280',
                    }}
                  />
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-xs text-bambu-gray/70">
                    {t('projectDetail.progress.percentComplete', { percent: platesProgressPercent.toFixed(0) })}
                  </span>
                  {stats?.remaining_prints != null && stats.remaining_prints > 0 && (
                    <span className="text-xs text-bambu-gray/70">
                      {t('projectDetail.progress.remaining', { count: stats.remaining_prints })}
                    </span>
                  )}
                </div>
              </div>
            )}
            {/* Parts progress */}
            {project.target_parts_count && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-bambu-gray">{t('projectDetail.progress.partsProgress')}</span>
                  <span className="text-sm font-medium text-white">
                    {stats?.completed_prints || 0} / {project.target_parts_count} {t('projectDetail.progress.parts')}
                  </span>
                </div>
                <div className="h-3 bg-bambu-dark rounded-full overflow-hidden">
                  <div
                    className="h-full transition-all duration-500"
                    style={{
                      width: `${Math.min(partsProgressPercent, 100)}%`,
                      backgroundColor: partsProgressPercent >= 100 ? '#22c55e' : project.color || '#6b7280',
                    }}
                  />
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-xs text-bambu-gray/70">
                    {t('projectDetail.progress.percentComplete', { percent: partsProgressPercent.toFixed(0) })}
                  </span>
                  {stats?.remaining_parts != null && stats.remaining_parts > 0 && (
                    <span className="text-xs text-bambu-gray/70">
                      {t('projectDetail.progress.remaining', { count: stats.remaining_parts })}
                    </span>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Stats grid */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-bambu-dark text-bambu-green">
                  <Package className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm text-bambu-gray">{t('projectDetail.stats.printJobs')}</p>
                  <p className="text-xl font-semibold text-white">{stats.total_archives} <span className="text-sm font-normal text-bambu-gray">{t('projectDetail.stats.total')}</span></p>
                  {stats.failed_prints > 0 && (
                    <p className="text-sm text-status-error">{t('projectDetail.stats.failed', { count: stats.failed_prints })}</p>
                  )}
                  <p className="text-sm text-bambu-gray">{t('projectDetail.stats.partsPrinted', { count: stats.completed_prints })}</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <StatCard
            icon={Clock}
            label={t('projectDetail.stats.printTime')}
            value={formatDurationFromHours(stats.total_print_time_hours)}
            color="text-yellow-400"
          />
          <StatCard
            icon={Printer}
            label={t('projectDetail.stats.filamentUsed')}
            value={formatFilament(stats.total_filament_grams)}
            color="text-purple-400"
          />
        </div>
      )}

      <ProductionPlan bomItems={bomItems || []} archives={archives || []} files={allProjectFiles || []} fileStates={productionFileStates} onStageFile={(file) => { setSchedulePrinterIds([]); setScheduleFile(file); }} />
      <DispatchSuggestions suggestions={dispatchSuggestions} onReview={(suggestion) => { setSchedulePrinterIds(suggestion.printer ? [suggestion.printer.id] : []); setScheduleFile(suggestion.file); }} />

      {/* Cost tracking */}
      {stats && (() => {
        const totalCost = stats.estimated_cost + stats.total_energy_cost + stats.bom_cost;
        return (stats.estimated_cost > 0 || totalCost > 0 || project.budget !== null);
      })() && (
        <Card>
          <CardContent className="p-4">
            <h2 className="text-lg font-semibold text-white mb-3">
              {t('projectDetail.cost.title')}
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-xs text-bambu-gray uppercase">{t('projectDetail.cost.filamentCost')}</p>
                <p className="text-lg font-semibold text-white">
                  {currency}{stats.estimated_cost.toFixed(2)}
                </p>
              </div>
              {stats.total_energy_kwh > 0 && (
                <div>
                  <p className="text-xs text-bambu-gray uppercase">{t('projectDetail.cost.energy')}</p>
                  <p className="text-lg font-semibold text-white">
                    {stats.total_energy_kwh.toFixed(3)} kWh
                    {stats.total_energy_cost > 0 && (
                      <span className="text-sm text-bambu-gray ml-1">
                        ({currency}{stats.total_energy_cost.toFixed(2)})
                      </span>
                    )}
                  </p>
                </div>
              )}
              {(() => {
                const totalCost = stats.estimated_cost + stats.total_energy_cost + stats.bom_cost;
                if (totalCost <= 0) return null;
                return (
                  <div>
                    <p className="text-xs text-bambu-gray uppercase">{t('projectDetail.cost.totalCost')}</p>
                    <p className="text-lg font-semibold text-bambu-green">
                      {currency}{totalCost.toFixed(2)}
                    </p>
                    {stats.bom_cost > 0 && (
                      <p className="text-xs text-bambu-gray/70">{t('projectDetail.cost.includesBom')}</p>
                    )}
                  </div>
                );
              })()}
              {project.budget !== null && (() => {
                const totalCost = stats.estimated_cost + stats.total_energy_cost + stats.bom_cost;
                const remaining = project.budget - totalCost;
                return (
                  <div>
                    <p className="text-xs text-bambu-gray uppercase">{t('projectDetail.cost.budget')}</p>
                    <p className="text-sm text-bambu-gray">
                      {t('projectDetail.cost.total')}: <span className="text-white font-semibold">{currency}{project.budget.toFixed(2)}</span>
                    </p>
                    <p className={`text-sm ${remaining >= 0 ? 'text-bambu-green' : 'text-red-400'}`}>
                      {t('projectDetail.cost.remaining')}: <span className="font-semibold">{currency}{remaining.toFixed(2)}</span>
                    </p>
                  </div>
                );
              })()}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sub-projects */}
      {project.children && project.children.length > 0 && (
        <Card>
          <CardContent className="p-4">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-3">
              <FolderTree className="w-5 h-5" />
              {t('projectDetail.subProjects.title', { count: project.children.length })}
            </h2>
            <div className="space-y-2">
              {project.children.map((child) => (
                <Link
                  key={child.id}
                  to={`/projects/${child.id}`}
                  className="flex items-center justify-between p-3 bg-bambu-dark rounded-lg hover:bg-bambu-dark-tertiary transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: child.color || '#6b7280' }}
                    />
                    <span className="text-white">{child.name}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      child.status === 'completed' ? 'bg-status-ok/20 text-status-ok' :
                      child.status === 'archived' ? 'bg-bambu-gray/20 text-bambu-gray' :
                      'bg-blue-500/20 text-blue-400'
                    }`}>
                      {child.status}
                    </span>
                  </div>
                  {child.progress_percent !== null && (
                    <span className="text-sm text-bambu-gray">
                      {child.progress_percent.toFixed(0)}%
                    </span>
                  )}
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Parent project link */}
      {project.parent_id && project.parent_name && (
        <div className="flex items-center gap-2 text-sm">
          <Layers className="w-4 h-4 text-bambu-gray" />
          <span className="text-bambu-gray">{t('projectDetail.partOf')}</span>
          <Link
            to={`/projects/${project.parent_id}`}
            className="text-bambu-green hover:underline"
          >
            {project.parent_name}
          </Link>
        </div>
      )}

      {/* Meta info row - Tags, Due Date, Priority */}
      {(project.tags || project.due_date || project.priority !== 'normal') && (
        <div className="flex flex-wrap items-center gap-4">
          {/* Priority */}
          {project.priority && project.priority !== 'normal' && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-bambu-gray uppercase">{t('projectDetail.priorityLabel')}</span>
              <PriorityBadge priority={project.priority} t={t} />
            </div>
          )}

          {/* Due Date */}
          {project.due_date && (
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4 text-bambu-gray" />
              <span className="text-sm text-white">{formatDateOnly(project.due_date, { year: 'numeric', month: 'short', day: 'numeric' })}</span>
              {getDueDateStatus(project.due_date, t) && (
                <span className={`text-xs ${getDueDateStatus(project.due_date, t)!.color}`}>
                  ({getDueDateStatus(project.due_date, t)!.label})
                </span>
              )}
            </div>
          )}

          {/* Tags */}
          {project.tags && (
            <div className="flex items-center gap-2">
              <Tag className="w-4 h-4 text-bambu-gray" />
              <div className="flex flex-wrap gap-1">
                {project.tags.split(',').map((tag, index) => (
                  <span
                    key={index}
                    className="px-2 py-0.5 bg-bambu-dark-tertiary text-bambu-gray text-xs rounded"
                  >
                    {tag.trim()}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Notes section */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <FileText className="w-5 h-5" />
              {t('projectDetail.notes.title')}
            </h2>
            {!editingNotes ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={handleStartEditNotes}
                disabled={!hasPermission('projects:update')}
                title={!hasPermission('projects:update') ? t('projectDetail.notes.noEditPermission') : undefined}
              >
                <Edit3 className="w-4 h-4 mr-1" />
                {t('common.edit')}
              </Button>
            ) : (
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleCancelNotes}
                  disabled={updateMutation.isPending}
                >
                  <X className="w-4 h-4 mr-1" />
                  {t('common.cancel')}
                </Button>
                <Button
                  size="sm"
                  onClick={handleSaveNotes}
                  disabled={updateMutation.isPending}
                >
                  {updateMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-1" />
                  ) : (
                    <Save className="w-4 h-4 mr-1" />
                  )}
                  {t('common.save')}
                </Button>
              </div>
            )}
          </div>

          {editingNotes ? (
            <RichTextEditor
              content={notesContent}
              onChange={setNotesContent}
              placeholder={t('projectDetail.notes.placeholder')}
            />
          ) : project.notes ? (
            <div
              className="prose prose-invert prose-sm max-w-none"
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(project.notes) }}
            />
          ) : (
            <p className="text-bambu-gray/70 text-sm italic">
              {t('projectDetail.notes.empty')}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Files section - linked folders from File Manager with printable files */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <FolderOpen className="w-5 h-5" />
              {t('projectDetail.files.title')}
            </h2>
          </div>

          <p className="text-xs text-bambu-gray mb-3">
            <Link to="/files" className="text-bambu-green hover:underline">
              {t('projectDetail.files.linkFolders')}
            </Link>
            {' '}{t('projectDetail.files.forQuickAccess')}
          </p>

          {linkedFolders && linkedFolders.length > 0 ? (
            <div className="space-y-4">
              {linkedFolders.map((folder) => {
                const files = filesByFolder.get(folder.id) ?? [];
                const isLoading = projectFilesLoading;

                return (
                  <div key={folder.id}>
                    {/* Folder header — links to File Manager */}
                    <Link
                      to={`/files?folder=${folder.id}`}
                      className="flex items-center justify-between p-3 bg-bambu-dark rounded-lg hover:bg-bambu-dark-tertiary transition-colors mb-2"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <FolderOpen className="w-5 h-5 text-bambu-green shrink-0" />
                        <div className="min-w-0">
                          <p className="text-sm text-white truncate">{folder.name}</p>
                          <p className="text-xs text-bambu-gray">
                            {t('projectDetail.files.fileCount', { count: folder.file_count })}
                          </p>
                        </div>
                      </div>
                      <ChevronRight className="w-4 h-4 text-bambu-gray shrink-0" />
                    </Link>

                    {/* File list within the folder */}
                    {isLoading ? (
                      <div className="flex items-center gap-2 px-3 py-2 text-bambu-gray text-sm">
                        <Loader2 className="w-4 h-4 animate-spin" />
                      </div>
                    ) : files.length === 0 ? (
                      <p className="text-bambu-gray/60 text-xs italic px-3">
                        {t('projectDetail.files.noFiles')}
                      </p>
                    ) : (
                      <div className="space-y-1 pl-3">
                        {files.map((file) => {
                          const printable = isSlicedFilename(file.filename);
                          return (
                            <div
                              key={file.id}
                              className="flex items-center gap-3 p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors"
                            >
                              {/* Thumbnail */}
                              <div className="w-10 h-10 shrink-0 rounded bg-bambu-dark overflow-hidden flex items-center justify-center">
                                {file.thumbnail_path ? (
                                  <img
                                    src={api.getLibraryFileThumbnailUrl(file.id)}
                                    alt={file.print_name || file.filename}
                                    className="w-full h-full object-cover"
                                  />
                                ) : (
                                  <FileBox className="w-5 h-5 text-bambu-gray/40" />
                                )}
                              </div>

                              {/* Name + type badge */}
                              <div className="flex-1 min-w-0">
                                <p className="text-sm text-white truncate" title={file.print_name || file.filename}>
                                  {file.print_name || file.filename}
                                </p>
                                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                                  file.file_type === '3mf' ? 'bg-bambu-green/20 text-bambu-green'
                                  : file.file_type === 'gcode' ? 'bg-blue-500/20 text-blue-400'
                                  : 'bg-bambu-gray/20 text-bambu-gray'
                                }`}>
                                  {file.file_type.toUpperCase()}
                                </span>
                              </div>

                              {/* Print actions for sliced files */}
                              {printable && (
                                <div className="flex items-center gap-1 shrink-0">
                                  <button
                                    onClick={() => setPrintFile(file)}
                                    title={t('projectDetail.files.print')}
                                    className="p-1.5 rounded hover:bg-bambu-green/20 text-bambu-green transition-colors"
                                  >
                                    <Play className="w-4 h-4" />
                                  </button>
                                  <button
                                    onClick={() => setScheduleFile(file)}
                                    title={t('projectDetail.files.addToQueue')}
                                    className="p-1.5 rounded hover:bg-blue-500/20 text-blue-400 transition-colors"
                                  >
                                    <CalendarPlus className="w-4 h-4" />
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-bambu-gray/70 text-sm italic">
              {t('projectDetail.files.empty')}
            </p>
          )}
        </CardContent>
      </Card>

      {/* BOM Section - Parts to source/purchase */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <ShoppingCart className="w-5 h-5" />
              {t('projectDetail.bom.title')}
              {stats && stats.bom_total_items > 0 && (
                <span className="text-sm font-normal text-bambu-gray">
                  ({t('projectDetail.bom.acquired', { completed: stats.bom_completed_items, total: stats.bom_total_items })})
                </span>
              )}
            </h2>
            <div className="flex items-center gap-2">
              {bomItems && bomItems.some(item => item.is_complete) && (
                <button
                  onClick={() => setHideBomCompleted(!hideBomCompleted)}
                  className={`text-xs px-2 py-1 rounded transition-colors ${
                    hideBomCompleted
                      ? 'bg-bambu-green/20 text-bambu-green'
                      : 'bg-bambu-dark text-bambu-gray hover:text-white'
                  }`}
                >
                  {hideBomCompleted ? t('projectDetail.bom.showAll') : t('projectDetail.bom.hideDone')}
                </button>
              )}
              {!showBomForm && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowBomForm(true)}
                  disabled={!hasPermission('projects:update')}
                  title={!hasPermission('projects:update') ? t('projectDetail.bom.noAddPermission') : undefined}
                >
                  <Plus className="w-4 h-4 mr-1" />
                  {t('projectDetail.bom.addPart')}
                </Button>
              )}
            </div>
          </div>

          {/* Add BOM item form */}
          {showBomForm && (
            <form onSubmit={handleAddBomItem} className="bg-bambu-dark rounded-lg p-4 mb-4 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <input
                  type="text"
                  value={newBomName}
                  onChange={(e) => setNewBomName(e.target.value)}
                  className="bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
                  placeholder={t('projectDetail.bom.partNamePlaceholder')}
                  autoFocus
                />
                <div className="flex gap-2">
                  <input
                    type="number"
                    value={newBomQty}
                    onChange={(e) => setNewBomQty(parseInt(e.target.value) || 1)}
                    className="w-20 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-bambu-green"
                    min="1"
                    placeholder={t('projectDetail.bom.qty')}
                  />
                  <input
                    type="number"
                    step="0.01"
                    value={newBomPrice}
                    onChange={(e) => setNewBomPrice(e.target.value)}
                    className="flex-1 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
                    placeholder={t('projectDetail.bom.price', { currency })}
                  />
                </div>
              </div>
              <input
                type="url"
                value={newBomUrl}
                onChange={(e) => setNewBomUrl(e.target.value)}
                className="w-full bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
                placeholder={t('projectDetail.bom.sourcingUrlPlaceholder')}
              />
              <input
                type="text"
                value={newBomRemarks}
                onChange={(e) => setNewBomRemarks(e.target.value)}
                className="w-full bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
                placeholder={t('projectDetail.bom.remarksPlaceholder')}
              />
              <div className="flex justify-end gap-2">
                <Button type="button" variant="secondary" size="sm" onClick={() => setShowBomForm(false)}>
                  {t('common.cancel')}
                </Button>
                <Button type="submit" size="sm" disabled={!newBomName.trim() || createBomMutation.isPending}>
                  {createBomMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    t('projectDetail.bom.addPart')
                  )}
                </Button>
              </div>
            </form>
          )}

          {bomLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-6 h-6 animate-spin text-bambu-green" />
            </div>
          ) : bomItems && bomItems.length > 0 ? (
            <div className="space-y-2">
              {bomItems
                .filter(item => !hideBomCompleted || !item.is_complete)
                .map((item) => (
                <div
                  key={item.id}
                  className={`p-3 rounded-lg transition-colors ${
                    item.is_complete ? 'bg-status-ok/10' : 'bg-bambu-dark'
                  }`}
                >
                  {editingBomItem?.id === item.id ? (
                    // Edit form for this BOM item
                    <form onSubmit={handleSaveBomEdit} className="space-y-3">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <input
                          type="text"
                          value={editBomName}
                          onChange={(e) => setEditBomName(e.target.value)}
                          className="bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
                          placeholder={t('projectDetail.bom.partName')}
                          autoFocus
                        />
                        <div className="flex gap-2">
                          <input
                            type="number"
                            value={editBomQty}
                            onChange={(e) => setEditBomQty(parseInt(e.target.value) || 1)}
                            className="w-20 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-bambu-green"
                            min="1"
                            placeholder={t('projectDetail.bom.qty')}
                          />
                          <input
                            type="number"
                            step="0.01"
                            value={editBomPrice}
                            onChange={(e) => setEditBomPrice(e.target.value)}
                            className="flex-1 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
                            placeholder={t('projectDetail.bom.price', { currency })}
                          />
                        </div>
                      </div>
                      <input
                        type="url"
                        value={editBomUrl}
                        onChange={(e) => setEditBomUrl(e.target.value)}
                        className="w-full bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
                        placeholder={t('projectDetail.bom.sourcingUrlPlaceholder')}
                      />
                      <input
                        type="text"
                        value={editBomRemarks}
                        onChange={(e) => setEditBomRemarks(e.target.value)}
                        className="w-full bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded px-3 py-2 text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
                        placeholder={t('projectDetail.bom.remarksPlaceholder')}
                      />
                      <div className="flex justify-end gap-2">
                        <Button type="button" variant="secondary" size="sm" onClick={handleCancelBomEdit}>
                          {t('common.cancel')}
                        </Button>
                        <Button type="submit" size="sm" disabled={!editBomName.trim() || updateBomMutation.isPending}>
                          {updateBomMutation.isPending ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            t('common.save')
                          )}
                        </Button>
                      </div>
                    </form>
                  ) : (
                    // Display mode
                    <div className="flex items-start gap-3">
                      <button
                        onClick={() => hasPermission('projects:update') && handleToggleAcquired(item)}
                        disabled={updateBomMutation.isPending || !hasPermission('projects:update')}
                        title={!hasPermission('projects:update') ? t('projectDetail.bom.noUpdatePermission') : undefined}
                        className={`w-5 h-5 mt-0.5 rounded border-2 flex items-center justify-center transition-colors shrink-0 ${
                          item.is_complete
                            ? 'bg-status-ok border-status-ok text-white'
                            : hasPermission('projects:update')
                              ? 'border-bambu-gray hover:border-bambu-green'
                              : 'border-bambu-gray/50 cursor-not-allowed'
                        }`}
                      >
                        {item.is_complete && <CheckCircle className="w-3 h-3" />}
                      </button>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <p className={`text-sm font-medium ${item.is_complete ? 'text-bambu-gray line-through' : 'text-white'}`}>
                              {item.name}
                              <span className="text-bambu-gray font-normal ml-2">
                                x{item.quantity_needed}
                              </span>
                            </p>
                            {item.unit_price !== null && (
                              <span className="text-xs text-bambu-green whitespace-nowrap">
                                {currency}{(item.unit_price * item.quantity_needed).toFixed(2)}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => hasPermission('projects:update') && handleEditBomItem(item)}
                              disabled={!hasPermission('projects:update')}
                              className={`p-1 rounded transition-colors shrink-0 ${
                                hasPermission('projects:update')
                                  ? 'hover:bg-bambu-dark-tertiary text-bambu-gray hover:text-white'
                                  : 'text-bambu-gray/50 cursor-not-allowed'
                              }`}
                              title={!hasPermission('projects:update') ? t('projectDetail.bom.noEditPermission') : t('common.edit')}
                            >
                              <Pencil className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => hasPermission('projects:update') && handleDeleteBomItem(item.id, item.name)}
                              disabled={!hasPermission('projects:update')}
                              className={`p-1 rounded transition-colors shrink-0 ${
                                hasPermission('projects:update')
                                  ? 'hover:bg-bambu-dark-tertiary text-bambu-gray hover:text-red-400'
                                  : 'text-bambu-gray/50 cursor-not-allowed'
                              }`}
                              title={!hasPermission('projects:update') ? t('projectDetail.bom.noDeletePermission') : t('common.delete')}
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                        {/* Sourcing URL */}
                        {item.sourcing_url && (
                          <a
                            href={item.sourcing_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1 mt-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ExternalLink className="w-3 h-3 shrink-0" />
                            <span className="truncate">
                              {(() => {
                                try {
                                  return new URL(item.sourcing_url).hostname.replace('www.', '');
                                } catch {
                                  return item.sourcing_url;
                                }
                              })()}
                            </span>
                          </a>
                        )}
                        {/* Remarks */}
                        {item.remarks && (
                          <p className="mt-1 text-xs text-bambu-gray/80 italic">
                            {item.remarks}
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {/* BOM Total */}
              {stats && stats.bom_cost > 0 && (
                <div className="pt-2 mt-2 border-t border-bambu-dark-tertiary flex justify-between text-sm">
                  <span className="text-bambu-gray">{t('projectDetail.bom.totalCost')}</span>
                  <span className="text-white font-medium">
                    {currency}{stats.bom_cost.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="text-bambu-gray/70 text-sm italic">
              {t('projectDetail.bom.empty')}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Timeline Section */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <History className="w-5 h-5" />
              {t('projectDetail.timeline.title')}
            </h2>
          </div>

          {timelineLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-6 h-6 animate-spin text-bambu-green" />
            </div>
          ) : timeline && timeline.length > 0 ? (
            <div className="space-y-3">
              {timeline.slice(0, 10).map((event, index) => (
                <div key={index} className="flex gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                    event.event_type === 'print_completed' ? 'bg-status-ok/20 text-status-ok' :
                    event.event_type === 'print_failed' ? 'bg-status-error/20 text-status-error' :
                    event.event_type === 'print_started' ? 'bg-yellow-500/20 text-yellow-400' :
                    'bg-bambu-dark-tertiary text-bambu-gray'
                  }`}>
                    {event.event_type === 'print_completed' && <CheckCircle className="w-4 h-4" />}
                    {event.event_type === 'print_failed' && <XCircle className="w-4 h-4" />}
                    {event.event_type === 'print_started' && <Printer className="w-4 h-4" />}
                    {event.event_type === 'queued' && <ListTodo className="w-4 h-4" />}
                    {event.event_type === 'project_created' && <Plus className="w-4 h-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white">{event.title}</p>
                    {event.description && (
                      <p className="text-xs text-bambu-gray truncate">{event.description}</p>
                    )}
                    <p className="text-xs text-bambu-gray/70">{formatTimelineDate(event.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-bambu-gray/70 text-sm italic">
              {t('projectDetail.timeline.empty')}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Template action */}
      {!project.is_template && (
        <div className="flex justify-end">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => createTemplateMutation.mutate()}
            disabled={createTemplateMutation.isPending || !hasPermission('projects:create')}
            title={!hasPermission('projects:create') ? t('projectDetail.template.noCreatePermission') : undefined}
          >
            {createTemplateMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin mr-2" />
            ) : (
              <Copy className="w-4 h-4 mr-2" />
            )}
            {t('projectDetail.template.saveAsTemplate')}
          </Button>
        </div>
      )}

      {/* Queue section */}
      {stats && (stats.queued_prints > 0 || stats.in_progress_prints > 0) && (
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                <ListTodo className="w-5 h-5" />
                {t('projectDetail.queue.title')}
              </h2>
              <Link
                to={`/queue?project=${projectId}`}
                className="text-sm text-bambu-green hover:underline"
              >
                {t('projectDetail.queue.viewAll')}
              </Link>
            </div>
            <div className="flex items-center gap-4 text-sm">
              {stats.in_progress_prints > 0 && (
                <span className="text-yellow-400">
                  {t('projectDetail.queue.printing', { count: stats.in_progress_prints })}
                </span>
              )}
              {stats.queued_prints > 0 && (
                <span className="text-bambu-gray">
                  {t('projectDetail.queue.queued', { count: stats.queued_prints })}
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Archives section */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Package className="w-5 h-5" />
            {t('projectDetail.prints.title', { count: archives?.length || 0 })}
          </h2>
        </div>
        {archivesLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-bambu-green" />
          </div>
        ) : (
          <ArchiveGrid archives={archives || []} t={t} />
        )}
      </div>

      {/* Edit Modal */}
      {showEditModal && (
        <ProjectModal
          t={t}
          currencySymbol={currency}
          project={{
            ...project,
            archive_count: stats?.total_archives || 0,
            total_items: stats?.total_items || 0,
            completed_count: stats?.completed_prints || 0,
            failed_count: stats?.failed_prints || 0,
            queue_count: stats?.queued_prints || 0,
            progress_percent: stats?.progress_percent || null,
            archives: [],
          }}
          onClose={() => setShowEditModal(false)}
          onSave={(data) => updateMutation.mutate(data as ProjectUpdate)}
          isLoading={updateMutation.isPending}
        />
      )}

      {/* Confirm Modal */}
      {confirmModal.isOpen && (
        <ConfirmModal
          title={confirmModal.title}
          message={confirmModal.message}
          confirmText={t('common.delete')}
          variant="danger"
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(prev => ({ ...prev, isOpen: false }))}
        />
      )}

      {/* Print directly from project — reprint mode */}
      {printFile && (
        <PrintModal
          mode="reprint"
          libraryFileId={printFile.id}
          archiveName={printFile.print_name || printFile.filename}
          projectId={projectId}
          onClose={() => setPrintFile(null)}
          onSuccess={() => {
            setPrintFile(null);
            queryClient.invalidateQueries({ queryKey: ['archives'] });
          }}
        />
      )}

      {/* Add to queue from project */}
      {scheduleFile && (
        <PrintModal
          mode="add-to-queue"
          libraryFileId={scheduleFile.id}
          archiveName={scheduleFile.print_name || scheduleFile.filename}
          initialSelectedPrinterIds={schedulePrinterIds}
          projectId={projectId}
          onClose={() => { setScheduleFile(null); setSchedulePrinterIds([]); }}
          onSuccess={() => {
            setScheduleFile(null);
            setSchedulePrinterIds([]);
            queryClient.invalidateQueries({ queryKey: ['queue'] });
          }}
        />
      )}
    </div>
  );
}
