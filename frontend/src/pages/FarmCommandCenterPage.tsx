import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueries, useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  ChevronRight,
  Grid3X3,
  Layers,
  Monitor,
  Pause,
  PackageOpen,
  Plus,
  Printer as PrinterIcon,
  Search,
  Server,
  Wrench,
  X,
} from 'lucide-react';
import {
  api,
  type InventorySpool,
  type MaintenanceStatus,
  type PrintQueueItem,
  type ProjectListItem,
  type Printer,
  type PrinterMaintenanceOverview,
  type PrinterStatus,
} from '../api/client';

interface FleetPrinter {
  printer: Printer;
  status?: PrinterStatus;
}

type FleetState = 'printing' | 'paused' | 'idle' | 'alert' | 'offline';

const REFRESH_MS = 15_000;
const PRINTER_GROUPS_STORAGE_KEY = 'printbuddy.commandCenterPrinterGroups';

interface CommandCenterPrinterGroup {
  id: string;
  name: string;
  printerIds: number[];
}

interface CommandCenterAlert {
  id: string;
  title: string;
  detail: string;
  tone: 'red' | 'amber' | 'blue';
}

function loadStoredPrinterGroups(): CommandCenterPrinterGroup[] {
  try {
    const raw = localStorage.getItem(PRINTER_GROUPS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((group): group is CommandCenterPrinterGroup => (
      typeof group?.id === 'string' && typeof group?.name === 'string' && Array.isArray(group?.printerIds)
    ));
  } catch {
    return [];
  }
}

function buildPrinterGroupMap(groups: CommandCenterPrinterGroup[]): Map<number, string> {
  const map = new Map<number, string>();
  groups.forEach((group) => group.printerIds.forEach((printerId) => map.set(printerId, group.name)));
  return map;
}

function normalizeState(status?: PrinterStatus): FleetState {
  if (!status || !status.connected) return 'offline';
  if ((status.hms_errors?.length ?? 0) > 0) return 'alert';
  const state = (status.state ?? '').toLowerCase();
  if (state.includes('error') || state.includes('fail')) return 'alert';
  if (state.includes('pause')) return 'paused';
  if (state.includes('print') || state.includes('run') || status.progress !== null || status.current_print) return 'printing';
  return 'idle';
}

function projectProgress(project: ProjectListItem): number | null {
  if (project.progress_percent !== null && project.progress_percent !== undefined) {
    return Math.min(100, Math.max(0, Math.round(project.progress_percent)));
  }
  if (project.target_parts_count && project.target_parts_count > 0) {
    return Math.min(100, Math.round((project.completed_count / project.target_parts_count) * 100));
  }
  if (project.target_count && project.target_count > 0) {
    return Math.min(100, Math.round((project.archive_count / project.target_count) * 100));
  }
  return null;
}

function projectTargetSummary(project: ProjectListItem): string {
  if (project.target_parts_count) return `${project.completed_count} / ${project.target_parts_count} Parts`;
  if (project.target_count) return `${project.archive_count} / ${project.target_count} Plates`;
  return `${project.archive_count} plates · ${project.completed_count} parts`;
}

function spoolRemainingPct(spool: InventorySpool): number | null {
  if (!spool.label_weight || spool.label_weight <= 0) return null;
  return Math.round((Math.max(0, spool.label_weight - (spool.weight_used ?? 0)) / spool.label_weight) * 100);
}

function lowSpoolCount(spools: InventorySpool[], defaultThreshold: number): number {
  return spools.filter((spool) => {
    if (spool.archived_at) return false;
    const remaining = spoolRemainingPct(spool);
    if (remaining === null) return false;
    return remaining <= (spool.low_stock_threshold_pct ?? defaultThreshold);
  }).length;
}

function maintenanceAttentionCount(overview: PrinterMaintenanceOverview[]): number {
  return overview.reduce((count, printer) => (
    count + printer.maintenance_items.filter((item: MaintenanceStatus) => item.enabled && (item.is_due || item.is_warning)).length
  ), 0);
}

function buildCommandCenterAlerts(fleet: FleetPrinter[], spools: InventorySpool[], maintenanceOverview: PrinterMaintenanceOverview[], defaultThreshold: number): CommandCenterAlert[] {
  const printerAlerts = fleet.flatMap((item) => {
    const state = normalizeState(item.status);
    const notices: CommandCenterAlert[] = [];
    if (state === 'alert') {
      notices.push({
        id: `printer-alert-${item.printer.id}`,
        title: item.printer.name,
        detail: item.status?.hms_errors?.length ? `${item.status.hms_errors.length} printer error${item.status.hms_errors.length === 1 ? '' : 's'} reported` : 'Printer reported an alert state',
        tone: 'red',
      });
    }
    if (state === 'paused') {
      notices.push({ id: `printer-paused-${item.printer.id}`, title: item.printer.name, detail: 'Paused - operator attention may be required', tone: 'amber' });
    }
    if (state === 'offline') {
      notices.push({ id: `printer-offline-${item.printer.id}`, title: item.printer.name, detail: 'Offline or unreachable', tone: 'red' });
    }
    return notices;
  });

  const stockAlerts = spools
    .filter((spool) => !spool.archived_at && spoolRemainingPct(spool) !== null && spoolRemainingPct(spool)! <= (spool.low_stock_threshold_pct ?? defaultThreshold))
    .map((spool) => ({
      id: `spool-${spool.id}`,
      title: `${spool.color_name ? `${spool.color_name} ` : ''}${spool.material}`,
      detail: `${spoolRemainingPct(spool)}% filament remaining`,
      tone: 'amber' as const,
    }));

  const maintenanceAlerts = maintenanceOverview.flatMap((printer) => printer.maintenance_items
    .filter((item: MaintenanceStatus) => item.enabled && (item.is_due || item.is_warning))
    .map((item: MaintenanceStatus, index: number) => ({
      id: `maintenance-${printer.printer_id}-${index}`,
      title: printer.printer_name,
      detail: item.maintenance_type_name || 'Maintenance item requires attention',
      tone: item.is_due ? 'red' as const : 'amber' as const,
    })));

  return [...printerAlerts, ...stockAlerts, ...maintenanceAlerts];
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDate(date: Date): string {
  return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}

function completedToday(queue: PrintQueueItem[], now: Date): number {
  const today = now.toDateString();
  return queue.filter((item) => item.status === 'completed' && item.completed_at && new Date(item.completed_at).toDateString() === today).length;
}

function StatCard({ icon: Icon, value, label, sub, tone, to, onClick }: { icon: typeof PrinterIcon; value: number | string; label: string; sub: string; tone: 'blue' | 'green' | 'gray' | 'amber' | 'purple'; to?: string; onClick?: () => void }) {
  const tones = {
    blue: 'bg-blue-500/15 text-blue-300 shadow-blue-500/10',
    green: 'bg-emerald-500/15 text-emerald-300 shadow-emerald-500/10',
    gray: 'bg-slate-500/15 text-slate-300 shadow-slate-500/10',
    amber: 'bg-amber-500/15 text-amber-300 shadow-amber-500/10',
    purple: 'bg-purple-500/15 text-purple-300 shadow-purple-500/10',
  };
  const content = (
    <>
      <div className="flex items-center gap-4">
        <div className={`flex h-14 w-14 items-center justify-center rounded-full shadow-lg ${tones[tone]}`}>
          <Icon className="h-7 w-7" />
        </div>
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white">{value}</span>
            <span className="text-xs font-semibold uppercase tracking-[0.2em] text-bambu-gray-light">{label}</span>
          </div>
          <div className="mt-1 text-sm font-semibold text-bambu-gray-light">{sub}</div>
        </div>
      </div>
      {(to || onClick) && <ChevronRight className="absolute right-4 top-4 h-4 w-4 text-bambu-gray transition-transform group-hover:translate-x-0.5 group-hover:text-white" />}
    </>
  );

  if (to) {
    return (
      <Link to={to} className="group relative block rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 shadow-[var(--card-shadow)] transition hover:border-blue-500 hover:bg-bambu-dark-secondary focus:outline-none focus:ring-2 focus:ring-blue-500">
        {content}
      </Link>
    );
  }

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className="group relative block w-full rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 text-left shadow-[var(--card-shadow)] transition hover:border-blue-500 hover:bg-bambu-dark-secondary focus:outline-none focus:ring-2 focus:ring-blue-500">
        {content}
      </button>
    );
  }

  return (
    <div className="relative rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 shadow-[var(--card-shadow)]">
      {content}
    </div>
  );
}

function FleetTile({ item }: { item: FleetPrinter }) {
  const state = normalizeState(item.status);
  const progress = item.status?.progress === null || item.status?.progress === undefined ? null : Math.min(100, Math.max(0, Math.round(item.status.progress)));
  const classes = {
    printing: 'border-blue-500/70 bg-blue-500/15 text-blue-200',
    paused: 'border-emerald-500/70 bg-emerald-500/15 text-emerald-200',
    idle: 'border-bambu-dark-tertiary bg-bambu-dark-secondary text-bambu-gray-light',
    alert: 'border-red-500/70 bg-red-500/15 text-red-200',
    offline: 'border-slate-700 bg-bambu-dark-secondary/70 text-bambu-gray',
  };
  const label = state === 'printing' ? 'Printing' : state === 'paused' ? 'Paused' : state === 'alert' ? 'Alert' : state === 'offline' ? 'Offline' : 'Idle';
  return (
    <div className={`min-h-20 rounded-lg border p-3 ${classes[state]}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-white">{item.printer.name}</div>
          <div className="mt-1 text-xs">{label}</div>
        </div>
        <span className="text-xs text-bambu-gray-light">{progress !== null ? `${progress}%` : '—'}</span>
      </div>
      {state === 'printing' && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-bambu-dark-tertiary">
          <div className="h-full rounded-full bg-blue-400" style={{ width: `${progress ?? 0}%` }} />
        </div>
      )}
    </div>
  );
}

function ActiveProjectCard({ project }: { project: ProjectListItem }) {
  const progress = projectProgress(project);
  return (
    <Link to={`/projects/${project.id}`} className="block rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 shadow-[var(--card-shadow)] transition hover:border-blue-500 hover:bg-bambu-dark-secondary focus:outline-none focus:ring-2 focus:ring-blue-500">
      <div className="flex gap-4">
        <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-bambu-dark-tertiary bg-bambu-dark">
          {project.cover_image_filename ? (
            <img src={api.getProjectCoverImageUrl(project.id)} alt="" className="h-full w-full object-cover" />
          ) : (
            <PackageOpen className="h-9 w-9 text-bambu-gray" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-base font-bold text-white">{project.name}</h3>
            <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-[0.65rem] font-bold uppercase text-emerald-300">Active</span>
          </div>
          {project.description && <p className="mt-1 truncate text-sm text-bambu-gray-light">{project.description}</p>}
          <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-bambu-gray-light">
            <span className="rounded-lg bg-bambu-dark px-2 py-1">{projectTargetSummary(project)}</span>
            {project.queue_count > 0 && <span className="rounded-lg bg-bambu-dark px-2 py-1">{project.queue_count} queued</span>}
            {project.failed_count > 0 && <span className="rounded-lg bg-red-500/15 px-2 py-1 text-red-300">{project.failed_count} failed</span>}
          </div>
        </div>
        <div className="w-20 shrink-0 text-right">
          <div className="text-2xl font-bold text-blue-400">{progress !== null ? `${progress}%` : '-'}</div>
          <div className="text-xs text-bambu-gray-light">Complete</div>
        </div>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-bambu-dark-tertiary">
        <div className="h-full rounded-full bg-blue-500" style={{ width: `${progress ?? 0}%` }} />
      </div>
    </Link>
  );
}

function AlertsDialog({ alerts, onClose }: { alerts: CommandCenterAlert[]; onClose: () => void }) {
  const toneClasses = {
    red: 'border-red-500/40 bg-red-500/10 text-red-200',
    amber: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    blue: 'border-blue-500/40 bg-blue-500/10 text-blue-200',
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="command-center-alerts-title">
      <div className="w-full max-w-2xl rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="command-center-alerts-title" className="text-xl font-bold text-white">Command Center Alerts</h2>
            <p className="text-sm text-bambu-gray-light">Printer, filament, and maintenance items that need attention.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close alerts" className="rounded-lg p-2 text-bambu-gray-light hover:bg-bambu-dark hover:text-white"><X className="h-5 w-5" /></button>
        </div>
        <div className="max-h-[60vh] space-y-3 overflow-y-auto">
          {alerts.length === 0 ? (
            <div className="rounded-xl border border-bambu-dark-tertiary bg-bambu-dark p-6 text-center text-bambu-gray-light">No active command center alerts.</div>
          ) : alerts.map((alert) => (
            <div key={alert.id} className={`rounded-xl border p-4 ${toneClasses[alert.tone]}`}>
              <div className="font-bold text-white">{alert.title}</div>
              <div className="mt-1 text-sm">{alert.detail}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PrinterGroupsDialog({ printers, groups, onSave, onClose }: { printers: Printer[]; groups: CommandCenterPrinterGroup[]; onSave: (groups: CommandCenterPrinterGroup[]) => void; onClose: () => void }) {
  const [name, setName] = useState('');
  const [selectedPrinterIds, setSelectedPrinterIds] = useState<number[]>([]);

  const togglePrinter = (printerId: number) => {
    setSelectedPrinterIds((current) => current.includes(printerId) ? current.filter((id) => id !== printerId) : [...current, printerId]);
  };

  const saveGroup = () => {
    const trimmed = name.trim();
    if (!trimmed || selectedPrinterIds.length === 0) return;
    const withoutAssigned = groups.map((group) => ({ ...group, printerIds: group.printerIds.filter((printerId) => !selectedPrinterIds.includes(printerId)) })).filter((group) => group.printerIds.length > 0 || group.name !== trimmed);
    const nextGroups = [...withoutAssigned, { id: `${Date.now()}`, name: trimmed, printerIds: selectedPrinterIds }];
    onSave(nextGroups);
    setName('');
    setSelectedPrinterIds([]);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="printer-groups-title">
      <div className="w-full max-w-2xl rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="printer-groups-title" className="text-xl font-bold text-white">Printer Groups</h2>
            <p className="text-sm text-bambu-gray-light">Create a fleet group and assign printers inside the command center.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close printer groups" className="rounded-lg p-2 text-bambu-gray-light hover:bg-bambu-dark hover:text-white"><X className="h-5 w-5" /></button>
        </div>
        <label className="mb-4 block text-sm font-semibold text-bambu-gray-light">
          Group name
          <input value={name} onChange={(event) => setName(event.target.value)} className="mt-2 w-full rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-white focus:border-blue-500 focus:outline-none" />
        </label>
        <div className="mb-4 grid gap-2 sm:grid-cols-2">
          {printers.map((printer) => (
            <label key={printer.id} className="flex items-center gap-3 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3 text-sm text-white">
              <input type="checkbox" checked={selectedPrinterIds.includes(printer.id)} onChange={() => togglePrinter(printer.id)} />
              <span>{printer.name}</span>
              <span className="ml-auto text-xs text-bambu-gray-light">{printer.location || 'Ungrouped'}</span>
            </label>
          ))}
        </div>
        {groups.length > 0 && (
          <div className="mb-4 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3 text-sm text-bambu-gray-light">
            <div className="mb-2 font-semibold text-white">Current command center groups</div>
            {groups.map((group) => <div key={group.id}>{group.name}: {group.printerIds.length} printer{group.printerIds.length === 1 ? '' : 's'}</div>)}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-bambu-dark-tertiary px-4 py-2 text-sm font-semibold text-bambu-gray-light hover:text-white">Cancel</button>
          <button type="button" onClick={saveGroup} disabled={!name.trim() || selectedPrinterIds.length === 0} className="rounded-lg bg-blue-500 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">Save Group</button>
        </div>
      </div>
    </div>
  );
}

export function FarmCommandCenterPage() {
  const [now, setNow] = useState(() => new Date());
  const [search, setSearch] = useState('');
  const [groupFilter, setGroupFilter] = useState('all');
  const [showAlerts, setShowAlerts] = useState(false);
  const [showGroups, setShowGroups] = useState(false);
  const [printerGroups, setPrinterGroups] = useState<CommandCenterPrinterGroup[]>(() => loadStoredPrinterGroups());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const { data: printers = [] } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters, refetchInterval: REFRESH_MS });
  const { data: queue = [] } = useQuery({ queryKey: ['queue', 'command-center'], queryFn: () => api.getQueue(), refetchInterval: REFRESH_MS });
  const { data: activeProjects = [] } = useQuery({ queryKey: ['projects', 'active', 'command-center'], queryFn: () => api.getProjects('active'), refetchInterval: REFRESH_MS, retry: false });
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.getSettings, staleTime: 60_000 });
  const { data: spools = [] } = useQuery({ queryKey: ['inventory-spools', 'command-center'], queryFn: () => api.getSpools(false), refetchInterval: REFRESH_MS, retry: false });
  const { data: maintenanceOverview = [] } = useQuery({ queryKey: ['maintenance-overview', 'command-center'], queryFn: api.getMaintenanceOverview, refetchInterval: REFRESH_MS, retry: false });
  const statusQueries = useQueries({
    queries: printers.map((printer) => ({
      queryKey: ['printerStatus', printer.id],
      queryFn: () => api.getPrinterStatus(printer.id),
      refetchInterval: REFRESH_MS,
      enabled: printer.is_active !== false,
    })),
  });

  const fleet = useMemo<FleetPrinter[]>(() => printers.map((printer, index) => ({ printer, status: statusQueries[index]?.data })), [printers, statusQueries]);
  const printerGroupMap = useMemo(() => buildPrinterGroupMap(printerGroups), [printerGroups]);
  const groupedFleet = useMemo(() => {
    const groups = new Map<string, FleetPrinter[]>();
    fleet.forEach((item) => {
      const name = printerGroupMap.get(item.printer.id) || item.printer.location?.trim() || 'Ungrouped';
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name)!.push(item);
    });
    return Array.from(groups.entries()).map(([name, items]) => ({ name, items }));
  }, [fleet, printerGroupMap]);

  const visibleGroups = groupedFleet
    .filter((group) => groupFilter === 'all' || group.name === groupFilter)
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => item.printer.name.toLowerCase().includes(search.toLowerCase())),
    }))
    .filter((group) => group.items.length > 0);

  const stateCounts = fleet.reduce<Record<FleetState, number>>((counts, item) => {
    counts[normalizeState(item.status)] += 1;
    return counts;
  }, { printing: 0, paused: 0, idle: 0, alert: 0, offline: 0 });

  const online = fleet.length - stateCounts.offline;
  const utilization = fleet.length > 0 ? Math.round((stateCounts.printing / fleet.length) * 100) : 0;
  const alertCount = stateCounts.alert + lowSpoolCount(spools, settings?.low_stock_threshold ?? 20) + maintenanceAttentionCount(maintenanceOverview);
  const todayParts = completedToday(queue as PrintQueueItem[], now);
  const visibleProjects = activeProjects.slice(0, 2);
  const lowStock = lowSpoolCount(spools, settings?.low_stock_threshold ?? 20);
  const maintenanceDue = maintenanceAttentionCount(maintenanceOverview);
  const commandCenterAlerts = useMemo(() => buildCommandCenterAlerts(fleet, spools, maintenanceOverview, settings?.low_stock_threshold ?? 20), [fleet, spools, maintenanceOverview, settings?.low_stock_threshold]);
  const savePrinterGroups = (nextGroups: CommandCenterPrinterGroup[]) => {
    setPrinterGroups(nextGroups);
    localStorage.setItem(PRINTER_GROUPS_STORAGE_KEY, JSON.stringify(nextGroups));
  };

  return (
    <div className="min-h-full bg-bambu-dark p-4 text-white xl:p-6">
      <div className="mx-auto max-w-[1700px] rounded-2xl border border-bambu-dark-tertiary bg-gradient-to-br from-bambu-dark-secondary/95 via-bambu-dark-secondary/80 to-bambu-dark p-5 shadow-[var(--card-shadow)]">
        <header className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="border-l-4 border-blue-500 pl-4">
            <h1 className="text-2xl font-bold tracking-tight text-white">Farm Command Center</h1>
            <p className="text-sm text-bambu-gray-light">Real-time overview of your 3D printing operation</p>
          </div>
          <div className="flex flex-col gap-3 xl:items-end">
            <div className="flex items-center gap-4">
              <span className="text-xs font-semibold uppercase tracking-[0.22em] text-bambu-gray">Fleet Utilization</span>
              <span className="text-3xl font-bold text-blue-400">{utilization}%</span>
              <div className="h-2 w-28 overflow-hidden rounded-full bg-bambu-dark-tertiary">
                <div className="h-full rounded-full bg-blue-500" style={{ width: `${utilization}%` }} />
              </div>
              <span className="text-xs text-bambu-gray-light">({stateCounts.printing} / {fleet.length})</span>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-3">
              <div className="text-right">
                <div className="font-mono text-3xl font-bold tracking-wider text-blue-300">{formatTime(now)}</div>
                <div className="text-xs text-bambu-gray-light">{formatDate(now)}</div>
              </div>
              <span className="inline-flex items-center gap-2 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-xs font-bold uppercase text-emerald-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400" /> Live
              </span>
              <Link to="/farm-monitor" className="inline-flex items-center gap-2 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-sm font-semibold text-bambu-gray-light hover:border-blue-500 hover:text-white">
                <Monitor className="h-4 w-4" /> TV Mode
              </Link>
            </div>
          </div>
        </header>

        <section className="mb-5 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <StatCard icon={Boxes} value={stateCounts.printing} label="Printing" sub={`${utilization}% of fleet`} tone="blue" />
          <StatCard icon={PrinterIcon} value={stateCounts.idle} label="Idle" sub={`${fleet.length ? Math.round((stateCounts.idle / fleet.length) * 100) : 0}% of fleet`} tone="gray" />
          <StatCard icon={Pause} value={stateCounts.paused} label="Paused" sub={`${fleet.length ? Math.round((stateCounts.paused / fleet.length) * 100) : 0}% of fleet`} tone="green" />
          <StatCard icon={AlertTriangle} value={alertCount} label="Alerts" sub="Printers, stock, maintenance" tone="amber" onClick={() => setShowAlerts(true)} />
          <StatCard icon={Layers} value={todayParts} label="Parts today" sub={`${queue.length} queue items tracked`} tone="purple" />
        </section>

        <section className="mb-5 rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark/50 p-4">
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-[0.22em] text-bambu-gray-light">Fleet Status</h2>
            <div className="flex flex-col gap-2 sm:flex-row">
              <label className="relative block">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-bambu-gray" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search printers..."
                  className="w-full rounded-lg border border-bambu-dark-tertiary bg-bambu-dark py-2 pl-9 pr-3 text-sm text-white placeholder-bambu-gray focus:border-blue-500 focus:outline-none sm:w-64"
                />
              </label>
              <select
                value={groupFilter}
                onChange={(event) => setGroupFilter(event.target.value)}
                className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
              >
                <option value="all">All Groups</option>
                {groupedFleet.map((group) => <option key={group.name} value={group.name}>{group.name}</option>)}
              </select>
              <button type="button" onClick={() => setShowGroups(true)} className="inline-flex items-center justify-center gap-2 rounded-lg border border-blue-500/60 bg-blue-500/10 px-3 py-2 text-sm font-semibold text-blue-300 transition hover:bg-blue-500/20 hover:text-white">
                <Plus className="h-4 w-4" /> Create Group
              </button>
              <div className="flex rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-1 text-bambu-gray-light">
                <span className="rounded bg-blue-500 px-3 py-1 text-white"><Grid3X3 className="h-4 w-4" /></span>
                <span className="px-3 py-1"><Server className="h-4 w-4" /></span>
              </div>
            </div>
          </div>

          <div className="space-y-3">
            {visibleGroups.map((group) => (
              <div key={group.name} className="grid gap-3 xl:grid-cols-[220px_1fr]">
                <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary/70 p-4">
                  <div className="flex items-center justify-between">
                    <div className="font-bold text-white">{group.name}</div>
                    <span className="rounded-full bg-bambu-dark-tertiary px-2 py-0.5 text-xs font-bold text-bambu-gray-light">{group.items.length}</span>
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-sm text-bambu-gray-light">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" /> {group.items.filter((item) => normalizeState(item.status) !== 'offline').length} Online
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8">
                  {group.items.slice(0, 8).map((item) => <FleetTile key={item.printer.id} item={item} />)}
                  {group.items.length > 8 && (
                    <div className="flex min-h-20 items-center justify-center rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary/70 text-sm text-bambu-gray-light">+{group.items.length - 8} more</div>
                  )}
                </div>
              </div>
            ))}
            {visibleGroups.length === 0 && (
              <div className="rounded-xl border border-dashed border-bambu-dark-tertiary p-8 text-center text-bambu-gray-light">No printers match the current filters.</div>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-bambu-dark-tertiary pt-4 text-sm text-bambu-gray-light">
            <div className="flex flex-wrap gap-4">
              <span className="flex items-center gap-2"><span className="h-2 w-2 rounded bg-blue-500" /> Printing</span>
              <span className="flex items-center gap-2"><span className="h-2 w-2 rounded bg-emerald-500" /> Paused</span>
              <span className="flex items-center gap-2"><span className="h-2 w-2 rounded bg-slate-400" /> Idle</span>
              <span className="flex items-center gap-2"><span className="h-2 w-2 rounded bg-red-500" /> Alert</span>
              <span className="flex items-center gap-2"><span className="h-2 w-2 rounded bg-slate-700" /> Offline</span>
            </div>
            <div className="flex flex-wrap gap-6">
              <span>{fleet.length} Total</span>
              <span className="text-emerald-300">{online} Online</span>
              <span>{stateCounts.offline} Offline</span>
            </div>
          </div>
        </section>

        <section className="mb-5 rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark/50 p-4">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-[0.22em] text-bambu-gray-light">Active Projects</h2>
            <Link to="/projects" className="inline-flex items-center gap-1 text-sm font-semibold text-blue-400 hover:text-blue-300">View all projects <ChevronRight className="h-4 w-4" /></Link>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            {visibleProjects.map((project) => <ActiveProjectCard key={project.id} project={project} />)}
            {visibleProjects.length === 0 && <div className="rounded-xl border border-dashed border-bambu-dark-tertiary p-8 text-center text-bambu-gray-light xl:col-span-2">No active projects are currently tracked.</div>}
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-3">
          <Link to="/notifications" className="group flex items-center gap-4 rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 transition hover:border-blue-500 hover:bg-bambu-dark-secondary focus:outline-none focus:ring-2 focus:ring-blue-500">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300"><CheckCircle2 className="h-7 w-7" /></div>
            <div className="min-w-0 flex-1"><div className="font-bold text-white">{alertCount === 0 ? 'All Systems Operational' : `${alertCount} item${alertCount === 1 ? '' : 's'} need attention`}</div><div className="text-sm text-bambu-gray-light">{alertCount === 0 ? 'No active system issues' : 'Open alerts and notification settings'}</div></div>
            <ChevronRight className="h-5 w-5 text-bambu-gray transition-transform group-hover:translate-x-0.5 group-hover:text-white" />
          </Link>
          <Link to="/inventory" className="group flex items-center gap-4 rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 transition hover:border-blue-500 hover:bg-bambu-dark-secondary focus:outline-none focus:ring-2 focus:ring-blue-500">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-bambu-dark-tertiary text-bambu-gray-light"><PackageOpen className="h-7 w-7" /></div>
            <div className="min-w-0 flex-1"><div className="font-bold text-white">Filament Stock</div><div className="text-sm text-bambu-gray-light">{lowStock} spool{lowStock === 1 ? '' : 's'} low in stock</div></div>
            <ChevronRight className="h-5 w-5 text-bambu-gray transition-transform group-hover:translate-x-0.5 group-hover:text-white" />
          </Link>
          <Link to="/maintenance" className="group flex items-center gap-4 rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 transition hover:border-blue-500 hover:bg-bambu-dark-secondary focus:outline-none focus:ring-2 focus:ring-blue-500">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-500/15 text-red-300"><Wrench className="h-7 w-7" /></div>
            <div className="min-w-0 flex-1"><div className="font-bold text-white">Maintenance</div><div className="text-sm text-bambu-gray-light">{maintenanceDue} maintenance item{maintenanceDue === 1 ? '' : 's'} require attention</div></div>
            <ChevronRight className="h-5 w-5 text-bambu-gray transition-transform group-hover:translate-x-0.5 group-hover:text-white" />
          </Link>
        </section>
      </div>
      {showAlerts && <AlertsDialog alerts={commandCenterAlerts} onClose={() => setShowAlerts(false)} />}
      {showGroups && <PrinterGroupsDialog printers={printers} groups={printerGroups} onSave={savePrinterGroups} onClose={() => setShowGroups(false)} />}
    </div>
  );
}
