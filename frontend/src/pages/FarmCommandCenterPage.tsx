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

function StatCard({ icon: Icon, value, label, sub, tone, to }: { icon: typeof PrinterIcon; value: number | string; label: string; sub: string; tone: 'blue' | 'green' | 'gray' | 'amber' | 'purple'; to?: string }) {
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
      {to && <ChevronRight className="absolute right-4 top-4 h-4 w-4 text-bambu-gray transition-transform group-hover:translate-x-0.5 group-hover:text-white" />}
    </>
  );

  if (to) {
    return (
      <Link to={to} className="group relative block rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 shadow-[var(--card-shadow)] transition hover:border-blue-500 hover:bg-bambu-dark-secondary focus:outline-none focus:ring-2 focus:ring-blue-500">
        {content}
      </Link>
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
    <article className="rounded-2xl border border-bambu-dark-tertiary bg-bambu-dark-secondary/80 p-4 shadow-[var(--card-shadow)]">
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
          <div className="text-2xl font-bold text-blue-400">{progress !== null ? `${progress}%` : '—'}</div>
          <div className="text-xs text-bambu-gray-light">Complete</div>
        </div>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-bambu-dark-tertiary">
        <div className="h-full rounded-full bg-blue-500" style={{ width: `${progress ?? 0}%` }} />
      </div>
    </article>
  );
}

export function FarmCommandCenterPage() {
  const [now, setNow] = useState(() => new Date());
  const [search, setSearch] = useState('');
  const [groupFilter, setGroupFilter] = useState('all');

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
  const groupedFleet = useMemo(() => {
    const groups = new Map<string, FleetPrinter[]>();
    fleet.forEach((item) => {
      const name = item.printer.location?.trim() || 'Ungrouped';
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name)!.push(item);
    });
    return Array.from(groups.entries()).map(([name, items]) => ({ name, items }));
  }, [fleet]);

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
          <StatCard icon={AlertTriangle} value={alertCount} label="Alerts" sub="Printers, stock, maintenance" tone="amber" to="/notifications" />
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
              <Link to="/groups/new" className="inline-flex items-center justify-center gap-2 rounded-lg border border-blue-500/60 bg-blue-500/10 px-3 py-2 text-sm font-semibold text-blue-300 transition hover:bg-blue-500/20 hover:text-white">
                <Plus className="h-4 w-4" /> Create Group
              </Link>
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
    </div>
  );
}
