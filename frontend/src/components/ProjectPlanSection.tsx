import { useIsMobile } from '../hooks/useIsMobile';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  CheckSquare,
  ClipboardList,
  Edit3,
  Layers,
  ListPlus,
  Loader2,
  Package,
  Plus,
  Search,
  Square,
  Trash2,
  X,
} from 'lucide-react';
import { api, withStreamToken } from '../api/client';
import type {
  InventorySpool,
  LibraryFileListItem,
  PlanFilament,
  PlanItem,
  PlanItemCreate,
  PlanItemUpdate,
  PlanSummary,
  Printer,
} from '../api/client';
import type { PlateMetadata } from '../types/plates';
import { Card, CardContent } from './Card';
import { Button } from './Button';
import { ConfirmModal } from './ConfirmModal';
import { useToast } from '../contexts/ToastContext';

const COMMON_MATERIALS = ['PLA', 'PLA-CF', 'PETG', 'PETG-CF', 'ABS', 'ASA', 'TPU', 'PA', 'PA-CF', 'PC', 'PVA', 'HIPS'];

function formatPlanDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return '–';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    const h = hours % 24;
    return h ? `${days}d ${h}h` : `${days}d`;
  }
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function formatPlanGrams(grams: number | null | undefined): string {
  if (grams === null || grams === undefined || Number.isNaN(grams) || grams <= 0) return '–';
  if (grams >= 1000) return `${(grams / 1000).toFixed(2)} kg`;
  return `${Math.round(grams)} g`;
}

function normalizeHex(color: string | null | undefined): string {
  if (!color) return '';
  let value = color.trim();
  if (!value.startsWith('#')) value = `#${value}`;
  if (value.length === 9) value = value.slice(0, 7);
  return value.toUpperCase();
}

function isValidHex(color: string): boolean {
  return /^#[0-9A-F]{6}$/i.test(color);
}

function displayFileName(filename: string): string {
  return filename.replace(/\.(gcode\.3mf|3mf|gcode|bgcode|stl)$/i, '');
}

type Assignment = string; // '' | 'p:<printerId>' | 'm:<model>'

function assignmentOf(item: { printer_id: number | null; target_model: string | null }): Assignment {
  if (item.printer_id) return `p:${item.printer_id}`;
  if (item.target_model) return `m:${item.target_model}`;
  return '';
}

function assignmentPayload(value: Assignment): Pick<PlanItemUpdate, 'printer_id' | 'target_model'> {
  if (value.startsWith('p:')) return { printer_id: Number(value.slice(2)), target_model: null };
  if (value.startsWith('m:')) return { printer_id: null, target_model: value.slice(2) };
  return { printer_id: null, target_model: null };
}

function AssignmentSelect({
  value,
  printers,
  onChange,
  disabled,
  className = '',
}: {
  value: Assignment;
  printers: Printer[];
  onChange: (value: Assignment) => void;
  disabled?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const models = useMemo(
    () => Array.from(new Set(printers.map((p) => p.model).filter((m): m is string => !!m))).sort(),
    [printers],
  );
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className={`rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1 text-sm text-white focus:border-bambu-green focus:outline-none ${className}`}
      aria-label={t('projectPlan.assignment')}
    >
      <option value="">{t('projectPlan.unassigned')}</option>
      {printers.length > 0 && (
        <optgroup label={t('projectPlan.printers')}>
          {printers.map((p) => (
            <option key={p.id} value={`p:${p.id}`}>
              {p.name}
            </option>
          ))}
        </optgroup>
      )}
      {models.length > 0 && (
        <optgroup label={t('projectPlan.printerModels')}>
          {models.map((m) => (
            <option key={m} value={`m:${m}`}>
              {t('projectPlan.anyModel', { model: m })}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}

function ColorSwatch({ color, size = 'w-4 h-4' }: { color: string; size?: string }) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full border border-white/20 ${size}`}
      style={{ backgroundColor: isValidHex(normalizeHex(color)) ? normalizeHex(color) : '#6b7280' }}
    />
  );
}

function FilamentChips({ filaments }: { filaments: PlanFilament[] }) {
  const { t } = useTranslation();
  if (filaments.length === 0) {
    return <span className="text-xs text-yellow-300">{t('projectPlan.noMaterial')}</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {filaments.map((f) => {
        const changed =
          !!f.original_type &&
          (f.type.toUpperCase() !== f.original_type.toUpperCase() ||
            normalizeHex(f.color) !== normalizeHex(f.original_color));
        return (
          <span
            key={f.slot_id}
            className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs ${changed ? 'bg-blue-500/15 text-blue-200' : 'bg-bambu-dark-tertiary text-bambu-gray-light'}`}
            title={changed ? t('projectPlan.overriddenFrom', { type: f.original_type, color: f.original_color }) : undefined}
          >
            <ColorSwatch color={f.color} size="w-3 h-3" />
            {f.type || '?'}
            {f.color_name ? ` · ${f.color_name}` : ''}
          </span>
        );
      })}
    </div>
  );
}

function ProgressCell({ item }: { item: PlanItem }) {
  const { t } = useTranslation();
  const p = item.progress;
  const total = Math.max(item.quantity, 1);
  const pct = (n: number) => `${Math.min(100, (n / total) * 100)}%`;
  return (
    <div className="min-w-[140px]">
      <div className="flex h-2 overflow-hidden rounded-full bg-bambu-dark">
        <div className="bg-bambu-green" style={{ width: pct(p.completed) }} />
        <div className="bg-blue-400" style={{ width: pct(p.printing) }} />
        <div className="bg-yellow-400/70" style={{ width: pct(p.queued) }} />
      </div>
      <div className="mt-1 flex flex-wrap gap-x-2 text-xs text-bambu-gray">
        <span className="text-white">
          {p.completed}/{item.quantity}
        </span>
        {p.printing > 0 && <span className="text-blue-300">{t('projectPlan.progressPrinting', { count: p.printing })}</span>}
        {p.queued > 0 && <span className="text-yellow-300">{t('projectPlan.progressQueued', { count: p.queued })}</span>}
        {p.failed > 0 && <span className="text-red-300">{t('projectPlan.progressFailed', { count: p.failed })}</span>}
        {p.remaining > 0 && <span>{t('projectPlan.progressOpen', { count: p.remaining })}</span>}
      </div>
    </div>
  );
}

function spoolHex(spool: InventorySpool): string {
  return normalizeHex(spool.rgba || '');
}

function spoolRemaining(spool: InventorySpool): number {
  return Math.max(0, (spool.label_weight || 0) - (spool.weight_used || 0));
}

// ---------------------------------------------------------------------------
// Edit modal: name, group, quantity, assignment, filaments, estimates, notes
// ---------------------------------------------------------------------------

function EditPlanItemModal({
  item,
  printers,
  spools,
  groups,
  onClose,
  onSave,
  saving,
}: {
  item: PlanItem;
  printers: Printer[];
  spools: InventorySpool[];
  groups: string[];
  onClose: () => void;
  onSave: (data: PlanItemUpdate) => void;
  saving: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(item.name);
  const [group, setGroup] = useState(item.group_label || '');
  const [quantity, setQuantity] = useState(item.quantity);
  const [assignment, setAssignment] = useState<Assignment>(assignmentOf(item));
  const [filaments, setFilaments] = useState<PlanFilament[]>(
    item.filaments.map((f) => ({ ...f, color: normalizeHex(f.color) || '#FFFFFF' })),
  );
  const [estMinutes, setEstMinutes] = useState(
    item.est_print_time_seconds ? String(Math.round(item.est_print_time_seconds / 60)) : '',
  );
  const [estGrams, setEstGrams] = useState(item.est_filament_grams ? String(item.est_filament_grams) : '');
  const [notes, setNotes] = useState(item.notes || '');

  const activeSpools = spools.filter((s) => spoolRemaining(s) > 0);

  const updateFilament = (index: number, patch: Partial<PlanFilament>) => {
    setFilaments((prev) => prev.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  };

  const handleSave = () => {
    const minutes = estMinutes.trim() === '' ? null : Math.max(0, Math.round(Number(estMinutes) * 60));
    const grams = estGrams.trim() === '' ? null : Math.max(0, Number(estGrams));
    onSave({
      name: name.trim() || item.name,
      group_label: group.trim() || null,
      quantity: Math.max(1, Math.round(quantity) || 1),
      filaments: filaments.map((f) => ({ ...f, type: f.type.trim(), color: normalizeHex(f.color) })),
      est_print_time_seconds: minutes !== null && Number.isFinite(minutes) ? minutes : null,
      est_filament_grams: grams !== null && Number.isFinite(grams) ? grams : null,
      notes: notes.trim() || null,
      ...assignmentPayload(assignment),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t('projectPlan.editPlate')}
      >
        <div className="flex items-center justify-between border-b border-bambu-dark-tertiary p-4">
          <h3 className="text-lg font-semibold text-white">{t('projectPlan.editPlate')}</h3>
          <button onClick={onClose} className="text-bambu-gray hover:text-white" aria-label={t('common.close')}>
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="space-y-4 p-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-sm text-bambu-gray">
              {t('projectPlan.name')}
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="mt-1 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-white focus:border-bambu-green focus:outline-none"
              />
            </label>
            <label className="block text-sm text-bambu-gray">
              {t('projectPlan.group')}
              <input
                value={group}
                list="plan-groups-edit"
                onChange={(e) => setGroup(e.target.value)}
                placeholder={t('projectPlan.groupPlaceholder')}
                className="mt-1 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-white focus:border-bambu-green focus:outline-none"
              />
              <datalist id="plan-groups-edit">
                {groups.map((g) => (
                  <option key={g} value={g} />
                ))}
              </datalist>
            </label>
            <label className="block text-sm text-bambu-gray">
              {t('projectPlan.quantity')}
              <input
                type="number"
                min={1}
                value={quantity}
                onChange={(e) => setQuantity(Number(e.target.value))}
                className="mt-1 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-white focus:border-bambu-green focus:outline-none"
              />
            </label>
            <label className="block text-sm text-bambu-gray">
              {t('projectPlan.assignment')}
              <AssignmentSelect value={assignment} printers={printers} onChange={setAssignment} className="mt-1 w-full py-2" />
            </label>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-sm font-semibold text-white">{t('projectPlan.materialsPerSlot')}</h4>
              <button
                type="button"
                onClick={() =>
                  setFilaments((prev) => [
                    ...prev,
                    { slot_id: (prev.reduce((m, f) => Math.max(m, f.slot_id), 0) || 0) + 1, type: 'PLA', color: '#FFFFFF' },
                  ])
                }
                className="inline-flex items-center gap-1 text-xs text-bambu-green hover:underline"
              >
                <Plus className="h-3.5 w-3.5" /> {t('projectPlan.addFilament')}
              </button>
            </div>
            {filaments.length === 0 && <p className="text-sm text-bambu-gray">{t('projectPlan.noFilamentsHint')}</p>}
            <div className="space-y-2">
              {filaments.map((f, index) => (
                <div key={`${f.slot_id}-${index}`} className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/60 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="w-14 text-xs text-bambu-gray">{t('projectPlan.slot', { slot: f.slot_id })}</span>
                    <input
                      value={f.type}
                      list="plan-materials"
                      onChange={(e) => updateFilament(index, { type: e.target.value })}
                      className="w-28 rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1 text-sm text-white focus:border-bambu-green focus:outline-none"
                      aria-label={t('projectPlan.material')}
                    />
                    <input
                      type="color"
                      value={isValidHex(normalizeHex(f.color)) ? normalizeHex(f.color) : '#FFFFFF'}
                      onChange={(e) => updateFilament(index, { color: e.target.value.toUpperCase() })}
                      className="h-8 w-10 cursor-pointer rounded border border-bambu-dark-tertiary bg-bambu-dark"
                      aria-label={t('projectPlan.color')}
                    />
                    <input
                      value={f.color_name || ''}
                      onChange={(e) => updateFilament(index, { color_name: e.target.value || null })}
                      placeholder={t('projectPlan.colorName')}
                      className="w-32 rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1 text-sm text-white focus:border-bambu-green focus:outline-none"
                    />
                    {activeSpools.length > 0 && (
                      <select
                        value=""
                        onChange={(e) => {
                          const spool = activeSpools.find((s) => s.id === Number(e.target.value));
                          if (spool) {
                            updateFilament(index, {
                              type: spool.material,
                              color: spoolHex(spool) || f.color,
                              color_name: spool.color_name || null,
                            });
                          }
                        }}
                        className="max-w-[12rem] rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1 text-xs text-bambu-gray-light focus:border-bambu-green focus:outline-none"
                        aria-label={t('projectPlan.fromInventory')}
                      >
                        <option value="">{t('projectPlan.fromInventory')}</option>
                        {activeSpools.map((s) => (
                          <option key={s.id} value={s.id}>
                            {[s.brand, s.material, s.color_name].filter(Boolean).join(' ')} ({Math.round(spoolRemaining(s))} g)
                          </option>
                        ))}
                      </select>
                    )}
                    <button
                      type="button"
                      onClick={() => setFilaments((prev) => prev.filter((_, i) => i !== index))}
                      className="ml-auto text-bambu-gray hover:text-red-400"
                      aria-label={t('common.delete')}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-3 pl-16 text-xs text-bambu-gray">
                    {f.original_type && (
                      <span className="inline-flex items-center gap-1">
                        {t('projectPlan.slicedWith')} <ColorSwatch color={f.original_color || ''} size="w-3 h-3" /> {f.original_type}
                      </span>
                    )}
                    <label className="inline-flex items-center gap-1">
                      {t('projectPlan.gramsPerCopy')}
                      <input
                        type="number"
                        min={0}
                        step="0.1"
                        value={f.used_grams ?? ''}
                        onChange={(e) =>
                          updateFilament(index, { used_grams: e.target.value === '' ? null : Number(e.target.value) })
                        }
                        className="w-20 rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 py-0.5 text-xs text-white focus:border-bambu-green focus:outline-none"
                      />
                    </label>
                  </div>
                </div>
              ))}
            </div>
            <datalist id="plan-materials">
              {COMMON_MATERIALS.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-sm text-bambu-gray">
              {t('projectPlan.estMinutes')}
              <input
                type="number"
                min={0}
                value={estMinutes}
                onChange={(e) => setEstMinutes(e.target.value)}
                className="mt-1 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-white focus:border-bambu-green focus:outline-none"
              />
            </label>
            <label className="block text-sm text-bambu-gray">
              {t('projectPlan.estGrams')}
              <input
                type="number"
                min={0}
                step="0.1"
                value={estGrams}
                onChange={(e) => setEstGrams(e.target.value)}
                className="mt-1 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-white focus:border-bambu-green focus:outline-none"
              />
            </label>
          </div>
          <label className="block text-sm text-bambu-gray">
            {t('projectPlan.notes')}
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-white focus:border-bambu-green focus:outline-none"
            />
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-bambu-dark-tertiary p-4">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('common.save')}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add modal: pick a file, its plates, quantity, group and assignment
// ---------------------------------------------------------------------------

function AddPlatesModal({
  projectFiles,
  printers,
  groups,
  onClose,
  onAdd,
  adding,
}: {
  projectFiles: LibraryFileListItem[];
  printers: Printer[];
  groups: string[];
  onClose: () => void;
  onAdd: (items: PlanItemCreate[]) => void;
  adding: boolean;
}) {
  const { t } = useTranslation();
  // Start with the files of the project's linked folders; the other library
  // files (not part of the project) are an opt-in second list.
  const [showAll, setShowAll] = useState(false);
  const [search, setSearch] = useState('');
  const [selectedFile, setSelectedFile] = useState<LibraryFileListItem | null>(null);
  const [selectedPlates, setSelectedPlates] = useState<Set<number>>(new Set());
  const [quantity, setQuantity] = useState(1);
  const [group, setGroup] = useState('');
  const [assignment, setAssignment] = useState<Assignment>('');

  const { data: allFiles = [], isLoading: allFilesLoading } = useQuery({
    queryKey: ['library-files-all-for-plan'],
    queryFn: () => api.getLibraryFiles(null, false),
    enabled: showAll,
  });

  const is3mf = !!selectedFile && selectedFile.filename.toLowerCase().endsWith('.3mf');
  const { data: platesData, isLoading: platesLoading } = useQuery({
    queryKey: ['library-file-plates', selectedFile?.id],
    queryFn: () => api.getLibraryFilePlates(selectedFile!.id),
    enabled: is3mf,
  });
  const plates: PlateMetadata[] = useMemo(() => platesData?.plates ?? [], [platesData]);

  const projectFileIds = useMemo(() => new Set(projectFiles.map((f) => f.id)), [projectFiles]);
  const otherFiles = useMemo(() => allFiles.filter((f) => !projectFileIds.has(f.id)), [allFiles, projectFileIds]);
  const files = (showAll ? otherFiles : projectFiles).filter((f) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return f.filename.toLowerCase().includes(q) || (f.print_name || '').toLowerCase().includes(q);
  });

  const selectFile = (file: LibraryFileListItem) => {
    setSelectedFile(file);
    setSelectedPlates(new Set());
  };

  const togglePlate = (index: number) => {
    setSelectedPlates((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const multiPlate = plates.length > 1;
  const canAdd = !!selectedFile && (!multiPlate || selectedPlates.size > 0);

  const handleAdd = () => {
    if (!selectedFile) return;
    const base = {
      library_file_id: selectedFile.id,
      quantity: Math.max(1, Math.round(quantity) || 1),
      group_label: group.trim() || null,
      ...assignmentPayload(assignment),
    };
    if (multiPlate) {
      onAdd(
        plates
          .filter((p) => selectedPlates.has(p.index))
          .map((p) => ({ ...base, plate_id: p.index })),
      );
    } else {
      onAdd([{ ...base, plate_id: plates.length === 1 ? plates[0].index : null }]);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t('projectPlan.addPlates')}
      >
        <div className="flex items-center justify-between border-b border-bambu-dark-tertiary p-4">
          <h3 className="text-lg font-semibold text-white">{t('projectPlan.addPlates')}</h3>
          <button onClick={onClose} className="text-bambu-gray hover:text-white" aria-label={t('common.close')}>
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 md:grid-cols-2">
          {/* File picker */}
          <div className="flex min-h-0 flex-col">
            <div className="mb-2 flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-bambu-gray" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('projectPlan.searchFiles')}
                  className="w-full rounded border border-bambu-dark-tertiary bg-bambu-dark py-1.5 pl-8 pr-2 text-sm text-white focus:border-bambu-green focus:outline-none"
                />
              </div>
            </div>
            <div className="mb-2 flex gap-1 text-xs">
              <button
                type="button"
                onClick={() => setShowAll(false)}
                className={`rounded px-2 py-1 ${!showAll ? 'bg-bambu-green/20 text-bambu-green' : 'text-bambu-gray hover:text-white'}`}
              >
                {t('projectPlan.projectFiles', { count: projectFiles.length })}
              </button>
              <button
                type="button"
                onClick={() => setShowAll(true)}
                className={`rounded px-2 py-1 ${showAll ? 'bg-bambu-green/20 text-bambu-green' : 'text-bambu-gray hover:text-white'}`}
              >
                {t('projectPlan.otherFiles')}
              </button>
            </div>
            <div className="max-h-80 min-h-[10rem] space-y-1 overflow-y-auto rounded border border-bambu-dark-tertiary bg-bambu-dark/50 p-1">
              {showAll && allFilesLoading && (
                <div className="flex justify-center p-4">
                  <Loader2 className="h-5 w-5 animate-spin text-bambu-gray" />
                </div>
              )}
              {files.length === 0 && !(showAll && allFilesLoading) && (
                !showAll && projectFiles.length === 0 ? (
                  <div className="p-3 text-sm text-bambu-gray">
                    <p>{t('projectPlan.noProjectFiles')}</p>
                    <button type="button" onClick={() => setShowAll(true)} className="mt-2 text-bambu-green hover:underline">
                      {t('projectPlan.showOtherFiles')}
                    </button>
                  </div>
                ) : (
                  <p className="p-3 text-sm text-bambu-gray">{t('projectPlan.noFiles')}</p>
                )
              )}
              {files.map((file) => (
                <button
                  key={file.id}
                  type="button"
                  onClick={() => selectFile(file)}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm ${selectedFile?.id === file.id ? 'bg-bambu-green/20 text-white' : 'text-bambu-gray-light hover:bg-bambu-dark-tertiary'}`}
                >
                  {file.thumbnail_path ? (
                    <img src={api.getLibraryFileThumbnailUrl(file.id)} alt="" className="h-8 w-8 rounded object-cover" />
                  ) : (
                    <Package className="h-8 w-8 p-1 text-bambu-gray" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{displayFileName(file.filename)}</span>
                    <span className="block text-xs text-bambu-gray">
                      {[formatPlanDuration(file.print_time_seconds), formatPlanGrams(file.filament_used_grams), file.filament_type]
                        .filter((v) => v && v !== '–')
                        .join(' · ') || t('projectPlan.notSlicedShort')}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Plate + options */}
          <div className="space-y-3">
            {!selectedFile && <p className="text-sm text-bambu-gray">{t('projectPlan.pickFileHint')}</p>}
            {selectedFile && (
              <>
                <div>
                  <p className="text-sm font-semibold text-white">{displayFileName(selectedFile.filename)}</p>
                  {platesLoading && <Loader2 className="mt-2 h-4 w-4 animate-spin text-bambu-gray" />}
                </div>
                {multiPlate && (
                  <div>
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span className="text-bambu-gray">{t('projectPlan.choosePlates')}</span>
                      <button
                        type="button"
                        className="text-bambu-green hover:underline"
                        onClick={() =>
                          setSelectedPlates(
                            selectedPlates.size === plates.length ? new Set() : new Set(plates.map((p) => p.index)),
                          )
                        }
                      >
                        {selectedPlates.size === plates.length ? t('projectPlan.selectNone') : t('projectPlan.selectAll')}
                      </button>
                    </div>
                    <div className="max-h-56 space-y-1 overflow-y-auto">
                      {plates.map((plate) => (
                        <button
                          key={plate.index}
                          type="button"
                          onClick={() => togglePlate(plate.index)}
                          className="flex w-full items-center gap-2 rounded border border-bambu-dark-tertiary px-2 py-1.5 text-left text-sm hover:bg-bambu-dark-tertiary"
                        >
                          {selectedPlates.has(plate.index) ? (
                            <CheckSquare className="h-4 w-4 text-bambu-green" />
                          ) : (
                            <Square className="h-4 w-4 text-bambu-gray" />
                          )}
                          {plate.has_thumbnail && plate.thumbnail_url ? (
                            <img src={withStreamToken(plate.thumbnail_url)} alt="" className="h-8 w-8 rounded object-cover" />
                          ) : (
                            <Layers className="h-8 w-8 p-1 text-bambu-gray" />
                          )}
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-white">
                              {plate.name || t('projectPlan.plateN', { n: plate.index })}
                            </span>
                            <span className="block text-xs text-bambu-gray">
                              {[formatPlanDuration(plate.print_time_seconds), formatPlanGrams(plate.filament_used_grams)]
                                .filter((v) => v !== '–')
                                .join(' · ')}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2">
                  <label className="block text-sm text-bambu-gray">
                    {t('projectPlan.quantity')}
                    <input
                      type="number"
                      min={1}
                      value={quantity}
                      onChange={(e) => setQuantity(Number(e.target.value))}
                      className="mt-1 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-3 py-1.5 text-white focus:border-bambu-green focus:outline-none"
                    />
                  </label>
                  <label className="block text-sm text-bambu-gray">
                    {t('projectPlan.group')}
                    <input
                      value={group}
                      list="plan-groups-add"
                      onChange={(e) => setGroup(e.target.value)}
                      placeholder={t('projectPlan.groupPlaceholder')}
                      className="mt-1 w-full rounded border border-bambu-dark-tertiary bg-bambu-dark px-3 py-1.5 text-white focus:border-bambu-green focus:outline-none"
                    />
                    <datalist id="plan-groups-add">
                      {groups.map((g) => (
                        <option key={g} value={g} />
                      ))}
                    </datalist>
                  </label>
                </div>
                <label className="block text-sm text-bambu-gray">
                  {t('projectPlan.assignment')}
                  <AssignmentSelect value={assignment} printers={printers} onChange={setAssignment} className="mt-1 w-full py-1.5" />
                </label>
                <p className="text-xs text-bambu-gray">{t('projectPlan.materialAfterAddHint')}</p>
              </>
            )}
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-bambu-dark-tertiary p-4">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleAdd} disabled={!canAdd || adding}>
            {adding ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
            {multiPlate
              ? t('projectPlan.addNPlates', { count: selectedPlates.size })
              : t('projectPlan.addPlate')}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Summary panel
// ---------------------------------------------------------------------------

function PlanSummaryPanel({ summary, spools }: { summary: PlanSummary; spools: InventorySpool[] }) {
  const { t } = useTranslation();
  const stockFor = (type: string, color: string) =>
    spools
      .filter((s) => s.material.toUpperCase() === type.toUpperCase() && spoolHex(s) === normalizeHex(color))
      .reduce((sum, s) => sum + spoolRemaining(s), 0);
  const pct = summary.progress_percent ?? 0;

  return (
    <div className="space-y-4 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/60 p-4">
      <div>
        <div className="mb-1 flex items-center justify-between text-sm">
          <span className="text-bambu-gray">{t('projectPlan.jobProgress')}</span>
          <span className="font-semibold text-white">
            {summary.completed_plates}/{summary.total_plates} · {pct.toFixed(0)}%
          </span>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-bambu-dark">
          <div className="h-full bg-bambu-green transition-all" style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-bambu-gray">
          {summary.printing_plates > 0 && <span className="text-blue-300">{t('projectPlan.progressPrinting', { count: summary.printing_plates })}</span>}
          {summary.queued_plates > 0 && <span className="text-yellow-300">{t('projectPlan.progressQueued', { count: summary.queued_plates })}</span>}
          {summary.failed_plates > 0 && <span className="text-red-300">{t('projectPlan.progressFailed', { count: summary.failed_plates })}</span>}
          {summary.remaining_plates > 0 && <span>{t('projectPlan.progressOpen', { count: summary.remaining_plates })}</span>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-xs text-bambu-gray">{t('projectPlan.totalPrintTime')}</p>
          <p className="font-semibold text-white">{formatPlanDuration(summary.planned_print_time_seconds)}</p>
          <p className="text-xs text-bambu-gray">
            {t('projectPlan.remainingValue', { value: formatPlanDuration(summary.remaining_print_time_seconds) })}
          </p>
        </div>
        <div>
          <p className="text-xs text-bambu-gray">{t('projectPlan.totalFilament')}</p>
          <p className="font-semibold text-white">{formatPlanGrams(summary.planned_filament_grams)}</p>
          <p className="text-xs text-bambu-gray">
            {t('projectPlan.remainingValue', { value: formatPlanGrams(summary.remaining_filament_grams) })}
          </p>
        </div>
      </div>
      {summary.unestimated_items > 0 && (
        <p className="flex items-start gap-1 text-xs text-yellow-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t('projectPlan.unestimatedHint', { count: summary.unestimated_items })}
        </p>
      )}

      {summary.materials.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase text-bambu-gray">{t('projectPlan.byMaterial')}</h4>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-bambu-gray">
                <th className="pb-1 text-left font-normal">{t('projectPlan.material')}</th>
                <th className="pb-1 text-right font-normal">{t('projectPlan.planned')}</th>
                <th className="pb-1 text-right font-normal">{t('projectPlan.remaining')}</th>
                {spools.length > 0 && <th className="pb-1 text-right font-normal">{t('projectPlan.inStock')}</th>}
              </tr>
            </thead>
            <tbody>
              {summary.materials.map((m) => {
                const stock = stockFor(m.type, m.color);
                const short = spools.length > 0 && m.remaining_grams > 0 && stock < m.remaining_grams;
                return (
                  <tr key={`${m.type}-${m.color}`} className="border-t border-bambu-dark-tertiary/60">
                    <td className="py-1.5">
                      <span className="inline-flex items-center gap-1.5 text-white">
                        <ColorSwatch color={m.color} />
                        {m.type}
                        {m.color_name && <span className="text-bambu-gray">· {m.color_name}</span>}
                      </span>
                    </td>
                    <td className="py-1.5 text-right text-white">{formatPlanGrams(m.planned_grams)}</td>
                    <td className="py-1.5 text-right text-bambu-gray-light">{formatPlanGrams(m.remaining_grams)}</td>
                    {spools.length > 0 && (
                      <td
                        className={`py-1.5 text-right ${short ? 'text-red-300' : 'text-bambu-gray-light'}`}
                        title={short ? t('projectPlan.notEnoughStock') : undefined}
                      >
                        {short && <AlertTriangle className="mr-1 inline h-3 w-3" />}
                        {stock > 0 ? formatPlanGrams(stock) : '0 g'}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export function ProjectPlanSection({
  projectId,
  projectFiles,
  printers,
  canEdit,
  canQueue,
}: {
  projectId: number;
  projectFiles: LibraryFileListItem[];
  printers: Printer[];
  canEdit: boolean;
  canQueue: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<PlanItem | null>(null);
  const [deleting, setDeleting] = useState<PlanItem | null>(null);
  const [stageOnly, setStageOnly] = useState(false);

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['project-plan', projectId],
    queryFn: () => api.getProjectPlan(projectId),
    enabled: projectId > 0,
    refetchInterval: 15000,
  });
  const { data: summary } = useQuery({
    queryKey: ['project-plan-summary', projectId],
    queryFn: () => api.getProjectPlanSummary(projectId),
    enabled: projectId > 0,
    refetchInterval: 15000,
  });
  const { data: spools = [] } = useQuery({
    queryKey: ['inventory-spools', 'project-plan'],
    queryFn: () => api.getSpools(false),
    retry: false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['project-plan', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project-plan-summary', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    queryClient.invalidateQueries({ queryKey: ['projects'] });
  };

  const addMutation = useMutation({
    mutationFn: async (rows: PlanItemCreate[]) => {
      for (const row of rows) {
        await api.createPlanItem(projectId, row);
      }
      return rows.length;
    },
    onSuccess: (count) => {
      invalidate();
      setShowAdd(false);
      showToast(t('projectPlan.addedToast', { count }), 'success');
    },
    onError: (error: Error) => {
      invalidate();
      showToast(error.message, 'error');
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: PlanItemUpdate }) => api.updatePlanItem(projectId, id, data),
    onSuccess: () => {
      invalidate();
      setEditing(null);
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deletePlanItem(projectId, id),
    onSuccess: () => {
      invalidate();
      setDeleting(null);
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const enqueueMutation = useMutation({
    mutationFn: (ids?: number[]) => api.enqueueProjectPlan(projectId, ids, stageOnly),
    onSuccess: (result) => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      const errors = result.results.filter((r) => r.error);
      if (result.queued_total > 0) {
        showToast(t('projectPlan.queuedToast', { count: result.queued_total }), 'success');
      }
      if (errors.length > 0) {
        const reasons = errors.map((r) => {
          const name = items.find((i) => i.id === r.plan_item_id)?.name || `#${r.plan_item_id}`;
          const reason =
            r.error === 'not_sliced'
              ? t('projectPlan.errorNotSliced')
              : r.error === 'file_missing'
                ? t('projectPlan.errorFileMissing')
                : r.error;
          return `${name}: ${reason}`;
        });
        showToast(reasons.join('\n'), 'error');
      } else if (result.queued_total === 0) {
        showToast(t('projectPlan.nothingToQueue'), 'info');
      }
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const groups = useMemo(
    () => Array.from(new Set(items.map((i) => i.group_label).filter((g): g is string => !!g))),
    [items],
  );
  const sections = useMemo(() => {
    const map = new Map<string, PlanItem[]>();
    for (const item of items) {
      const key = item.group_label || '';
      map.set(key, [...(map.get(key) || []), item]);
    }
    return Array.from(map.entries());
  }, [items]);

  const openToQueue = items.reduce((sum, i) => sum + i.progress.remaining, 0);

  // Cell renderers shared by the desktop table and the mobile card list
  const isMobile = useIsMobile();
  const planCell = {
    plate: (item: PlanItem) => (
      <>
        <div className="flex items-center gap-2">
          {item.thumbnail_url ? (
            <img
              src={withStreamToken(item.thumbnail_url)}
              alt=""
              className="h-10 w-10 shrink-0 rounded object-cover"
              onError={(e) => {
                const img = e.currentTarget;
                if (item.library_file_id && !img.dataset.fallback) {
                  img.dataset.fallback = '1';
                  img.src = api.getLibraryFileThumbnailUrl(item.library_file_id);
                } else {
                  img.style.visibility = 'hidden';
                }
              }}
            />
          ) : (
            <Package className="h-10 w-10 shrink-0 p-2 text-bambu-gray" />
          )}
          <div className="min-w-0">
            <p className="truncate font-medium text-white">{item.name}</p>
            {item.library_file_missing ? (
              <p className="text-xs text-red-300">{t('projectPlan.errorFileMissing')}</p>
            ) : !item.is_sliced && item.library_file_id ? (
              <p className="text-xs text-yellow-300">{t('projectPlan.errorNotSliced')}</p>
            ) : item.notes ? (
              <p className="truncate text-xs text-bambu-gray">{item.notes}</p>
            ) : null}
          </div>
        </div>
      </>
    ),
    material: (item: PlanItem) => (
      <>
        <FilamentChips filaments={item.filaments} />
      </>
    ),
    quantity: (item: PlanItem) => (
      <>
        {canEdit ? (
          <input
            key={`${item.id}-${item.quantity}`}
            type="number"
            min={1}
            defaultValue={item.quantity}
            onBlur={(e) => {
              const value = Math.max(1, Math.round(Number(e.target.value)) || 1);
              if (value !== item.quantity) updateMutation.mutate({ id: item.id, data: { quantity: value } });
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
            className="w-16 rounded border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1 text-white focus:border-bambu-green focus:outline-none"
            aria-label={t('projectPlan.quantity')}
          />
        ) : (
          <span className="text-white">{item.quantity}</span>
        )}
      </>
    ),
    assignment: (item: PlanItem) => (
      <>
        <AssignmentSelect
          value={assignmentOf(item)}
          printers={printers}
          disabled={!canEdit}
          onChange={(value) => updateMutation.mutate({ id: item.id, data: assignmentPayload(value) })}
          className="max-w-[11rem]"
        />
      </>
    ),
    estimate: (item: PlanItem) => (
      <>
        <div>{formatPlanDuration((item.est_print_time_seconds || 0) * item.quantity)}</div>
        <div className="text-xs text-bambu-gray">
          {formatPlanGrams(
            (item.est_filament_grams ??
              item.filaments.reduce((s, f) => s + (f.used_grams || 0), 0)) * item.quantity,
          )}
        </div>
      </>
    ),
    progress: (item: PlanItem) => (
      <>
        <ProgressCell item={item} />
      </>
    ),
    actions: (item: PlanItem) => (
      <>
        <div className="inline-flex items-center gap-1">
          {canQueue && item.progress.remaining > 0 && item.is_sliced && (
            <button
              type="button"
              onClick={() => enqueueMutation.mutate([item.id])}
              disabled={enqueueMutation.isPending}
              className="rounded p-1.5 text-blue-300 hover:bg-blue-500/15"
              title={t('projectPlan.queueRow', { count: item.progress.remaining })}
              aria-label={t('projectPlan.queueRow', { count: item.progress.remaining })}
            >
              <ListPlus className="h-4 w-4" />
            </button>
          )}
          {canEdit && (
          <>
              <button
                type="button"
                onClick={() => setEditing(item)}
                className="rounded p-1.5 text-bambu-gray hover:bg-bambu-dark-tertiary hover:text-white"
                title={t('projectPlan.editPlate')}
                aria-label={t('projectPlan.editPlate')}
              >
                <Edit3 className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setDeleting(item)}
                className="rounded p-1.5 text-bambu-gray hover:bg-red-500/15 hover:text-red-400"
                title={t('common.delete')}
                aria-label={t('common.delete')}
              >
                <Trash2 className="h-4 w-4" />
              </button>
          </>
        )}
      </div>
      </>
    ),
  };

  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
              <ClipboardList className="h-5 w-5" />
              {t('projectPlan.title')}
            </h2>
            <p className="mt-1 text-xs text-bambu-gray">{t('projectPlan.subtitle')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canQueue && items.length > 0 && (
              <label className="inline-flex items-center gap-1.5 text-xs text-bambu-gray" title={t('projectPlan.stageOnlyHint')}>
                <input type="checkbox" checked={stageOnly} onChange={(e) => setStageOnly(e.target.checked)} />
                {t('projectPlan.stageOnly')}
              </label>
            )}
            {canQueue && items.length > 0 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => enqueueMutation.mutate(undefined)}
                disabled={openToQueue === 0 || enqueueMutation.isPending}
              >
                {enqueueMutation.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <ListPlus className="mr-1.5 h-4 w-4" />}
                {t('projectPlan.queueAll', { count: openToQueue })}
              </Button>
            )}
            {canEdit && (
              <Button size="sm" onClick={() => setShowAdd(true)}>
                <Plus className="mr-1.5 h-4 w-4" />
                {t('projectPlan.addPlates')}
              </Button>
            )}
          </div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-6">
            <Loader2 className="h-6 w-6 animate-spin text-bambu-gray" />
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-bambu-dark-tertiary py-8 text-center text-bambu-gray">
            <ClipboardList className="mx-auto mb-2 h-10 w-10 opacity-50" />
            <p className="text-sm">{t('projectPlan.empty')}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0 space-y-4">
              {sections.map(([groupName, groupItems]) => (
                <div key={groupName || '__none'}>
                  {(sections.length > 1 || groupName) && (
                    <h3 className="mb-2 text-sm font-semibold text-bambu-gray-light">
                      {groupName || t('projectPlan.ungrouped')}{' '}
                      <span className="font-normal text-bambu-gray">
                        ({groupItems.reduce((s, i) => s + i.quantity, 0)})
                      </span>
                    </h3>
                  )}
                  {/* Phones: one card per plate instead of a 7-column table */}
                  {isMobile ? (
                  <ul className="space-y-2">
                    {groupItems.map((item) => (
                      <li key={item.id} className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/40 p-3 text-sm">
                        <div className="flex items-start gap-2">
                          <div className="min-w-0 flex-1">{planCell.plate(item)}</div>
                          <div className="shrink-0 -mr-1.5 -mt-1">{planCell.actions(item)}</div>
                        </div>
                        <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5">
                          <div className="col-span-2">
                            <p className="mb-1 text-[11px] uppercase text-bambu-gray">{t('projectPlan.material')}</p>
                            {planCell.material(item)}
                          </div>
                          <div>
                            <p className="mb-1 text-[11px] uppercase text-bambu-gray">{t('projectPlan.quantity')}</p>
                            {planCell.quantity(item)}
                          </div>
                          <div className="text-bambu-gray-light">
                            <p className="mb-1 text-[11px] uppercase text-bambu-gray">{t('projectPlan.estimate')}</p>
                            {planCell.estimate(item)}
                          </div>
                          <div className="col-span-2">
                            <p className="mb-1 text-[11px] uppercase text-bambu-gray">{t('projectPlan.assignment')}</p>
                            {planCell.assignment(item)}
                          </div>
                          <div className="col-span-2">
                            <p className="mb-1 text-[11px] uppercase text-bambu-gray">{t('projectPlan.progress')}</p>
                            {planCell.progress(item)}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                  ) : (
                  <div className="overflow-x-auto rounded-lg border border-bambu-dark-tertiary">
                    <table className="w-full text-sm">
                      <thead className="bg-bambu-dark-tertiary text-xs uppercase text-bambu-gray">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">{t('projectPlan.plate')}</th>
                          <th className="px-3 py-2 text-left font-medium">{t('projectPlan.material')}</th>
                          <th className="px-3 py-2 text-left font-medium">{t('projectPlan.quantity')}</th>
                          <th className="px-3 py-2 text-left font-medium">{t('projectPlan.assignment')}</th>
                          <th className="px-3 py-2 text-left font-medium">{t('projectPlan.estimate')}</th>
                          <th className="px-3 py-2 text-left font-medium">{t('projectPlan.progress')}</th>
                          <th className="px-3 py-2 text-right font-medium" />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-bambu-dark-tertiary">
                        {groupItems.map((item) => (
                          <tr key={item.id} className="align-top">
                            <td className="px-3 py-2">{planCell.plate(item)}</td>
                            <td className="px-3 py-2">{planCell.material(item)}</td>
                            <td className="px-3 py-2">{planCell.quantity(item)}</td>
                            <td className="px-3 py-2">{planCell.assignment(item)}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-bambu-gray-light">{planCell.estimate(item)}</td>
                            <td className="px-3 py-2">{planCell.progress(item)}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-right">{planCell.actions(item)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  )}
                </div>
              ))}
            </div>
            {summary && <PlanSummaryPanel summary={summary} spools={spools} />}
          </div>
        )}
      </CardContent>

      {showAdd && (
        <AddPlatesModal
          projectFiles={projectFiles}
          printers={printers}
          groups={groups}
          onClose={() => setShowAdd(false)}
          onAdd={(rows) => addMutation.mutate(rows)}
          adding={addMutation.isPending}
        />
      )}
      {editing && (
        <EditPlanItemModal
          item={editing}
          printers={printers}
          spools={spools}
          groups={groups}
          onClose={() => setEditing(null)}
          onSave={(data) => updateMutation.mutate({ id: editing.id, data })}
          saving={updateMutation.isPending}
        />
      )}
      {deleting && (
        <ConfirmModal
          title={t('projectPlan.deleteTitle')}
          message={t('projectPlan.deleteMessage', { name: deleting.name })}
          confirmText={t('common.delete')}
          variant="danger"
          onConfirm={() => deleteMutation.mutate(deleting.id)}
          onCancel={() => setDeleting(null)}
        />
      )}
    </Card>
  );
}
