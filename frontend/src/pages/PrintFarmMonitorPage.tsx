import { useMemo } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  CirclePause,
  Clock3,
  Layers,
  PackageOpen,
  PauseCircle,
  PlayCircle,
  Power,
  Printer as PrinterIcon,
  RefreshCw,
  Server,
  Thermometer,
  TriangleAlert,
  Wrench,
} from 'lucide-react';
import { api, type PrintQueueItem, type Printer, type PrinterStatus } from '../api/client';
import { getPrinterImage } from '../utils/printer';
import { appAssetPath } from '../utils/assetPaths';

interface MonitorPrinter {
  printer: Printer;
  status?: PrinterStatus;
}

type NormalizedState = 'printing' | 'idle' | 'paused' | 'offline' | 'error';

const DEMO_SPOOLS = [
  { material: 'PLA Matte Black', spool: 'Spool A1', color: 'bg-zinc-500' },
  { material: 'PETG Orange', spool: 'Spool A1', color: 'bg-orange-500' },
  { material: 'PLA White', spool: 'Spool B1', color: 'bg-zinc-100' },
  { material: 'ABS Gray', spool: 'Spool B2', color: 'bg-zinc-400' },
  { material: 'PLA Blue', spool: 'Spool C1', color: 'bg-sky-500' },
  { material: 'PETG Black', spool: 'Spool D1', color: 'bg-zinc-700' },
];

function normalizeState(status?: PrinterStatus): NormalizedState {
  if (!status || !status.connected) return 'offline';
  const state = (status.state ?? '').toLowerCase();
  if (state.includes('pause')) return 'paused';
  if (state.includes('error') || state.includes('fail')) return 'error';
  if (state.includes('print') || state.includes('run') || status.progress !== null || status.current_print) return 'printing';
  return 'idle';
}

function formatClock(date = new Date()): string {
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function formatDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return '—';
  const rounded = Math.max(0, Math.round(minutes));
  if (rounded < 60) return `${rounded}m`;
  const hours = Math.floor(rounded / 60);
  const mins = rounded % 60;
  return mins ? `${hours}h ${mins}m` : `${hours}h`;
}

function formatEta(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return 'Ready';
  const eta = new Date(Date.now() + Math.max(0, minutes) * 60_000);
  return eta.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function getJobName(item: MonitorPrinter, index: number): string {
  return item.status?.current_print || item.status?.subtask_name || item.status?.gcode_file || [
    'Gridfinity Calibration Tray',
    'Honeycomb Desk Organizer',
    'Cable Pass-Through Plates',
    'Voron Test Cube',
  ][index % 4];
}

function getLocation(printer: Printer, index: number): string {
  return printer.location || [`Rack A-01`, `Rack A-02`, `Rack B-01`, `Rack B-02`, `Rack C-01`, `Rack C-02`, `Rack D-01`, `Rack D-02`][index % 8];
}

function getSpool(index: number) {
  return DEMO_SPOOLS[index % DEMO_SPOOLS.length];
}

function StatTile({ icon: Icon, label, value, tone = 'blue', suffix }: { icon: typeof PrinterIcon; label: string; value: string | number; tone?: 'blue' | 'green' | 'gray' | 'purple' | 'amber'; suffix?: string }) {
  const toneClasses = {
    blue: 'bg-blue-500/15 text-blue-400',
    green: 'bg-emerald-500/15 text-emerald-400',
    gray: 'bg-slate-500/20 text-slate-300',
    purple: 'bg-purple-500/15 text-purple-300',
    amber: 'bg-amber-500/15 text-amber-300',
  };

  return (
    <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-slate-900/75 px-4 py-3 shadow-[0_0_30px_rgba(15,23,42,0.35)]">
      <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${toneClasses[tone]}`}>
        <Icon className="h-6 w-6" />
      </div>
      <div className="min-w-0">
        <div className="text-[0.65rem] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
        <div className="flex items-baseline gap-1 text-2xl font-bold text-white">
          {value}{suffix && <span className="text-sm font-semibold text-slate-300">{suffix}</span>}
        </div>
      </div>
    </div>
  );
}

function PrinterCard({ item, index }: { item: MonitorPrinter; index: number }) {
  const { printer, status } = item;
  const state = normalizeState(status);
  const progress = Math.min(100, Math.max(0, Math.round(status?.progress ?? (state === 'printing' ? [42, 29, 67, 81][index % 4] : 0))));
  const spool = getSpool(index);
  const nozzle = Math.round(status?.temperatures?.nozzle ?? (state === 'printing' ? 205 + (index % 4) * 3 : 27 + index));
  const bed = Math.round(status?.temperatures?.bed ?? (state === 'printing' ? 58 + (index % 3) : 26 + (index % 3)));
  const layer = status?.layer_num ?? (state === 'printing' ? 58 + index * 26 : null);
  const totalLayers = status?.total_layers ?? (state === 'printing' ? 198 + index * 2 : null);

  const stateClasses = {
    printing: 'bg-emerald-500/15 text-emerald-300 shadow-emerald-500/20',
    idle: 'bg-blue-500/15 text-blue-300 shadow-blue-500/20',
    paused: 'bg-amber-500/15 text-amber-300 shadow-amber-500/20',
    offline: 'bg-slate-500/15 text-slate-300 shadow-slate-500/20',
    error: 'bg-red-500/15 text-red-300 shadow-red-500/20',
  };
  const stateLabel = state === 'printing' ? 'PRINTING' : state === 'paused' ? 'PAUSED' : state === 'offline' ? 'OFFLINE' : state === 'error' ? 'ERROR' : 'IDLE';

  return (
    <article className="rounded-2xl border border-white/10 bg-slate-950/70 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04),0_20px_45px_rgba(0,0,0,0.25)]">
      <div className="flex gap-4">
        <div className="flex h-20 w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-white/10 bg-black/30 p-1.5">
          {state === 'offline' ? <TriangleAlert className="h-9 w-9 text-red-400" /> : <img src={getPrinterImage(printer.model)} alt="" className="max-h-full max-w-full object-contain" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className={`mb-3 inline-flex items-center gap-2 rounded-lg px-3 py-1 text-xs font-bold shadow-lg ${stateClasses[state]}`}>
            <span className={`h-2 w-2 rounded-full ${state === 'printing' ? 'bg-emerald-400' : state === 'paused' ? 'bg-amber-400' : state === 'offline' ? 'bg-slate-400' : state === 'error' ? 'bg-red-400' : 'bg-blue-400'}`} />
            {stateLabel}
          </div>
          <h2 className="truncate text-lg font-bold text-white">{printer.name}</h2>
          <p className="truncate text-sm text-slate-400">{printer.model || printer.provider || 'Printer'}</p>
          <p className="truncate text-sm text-slate-400">{getLocation(printer, index)}</p>
        </div>
      </div>

      {state === 'printing' ? (
        <div className="mt-5 space-y-3">
          <div>
            <div className="mb-1 text-[0.68rem] font-semibold uppercase text-slate-500">Current job</div>
            <div className="flex items-end justify-between gap-3">
              <div className="truncate font-semibold text-white">{getJobName(item, index)}</div>
              <div className="text-2xl font-bold text-white">{progress}%</div>
            </div>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-slate-800">
            <div className="h-full rounded-full bg-gradient-to-r from-sky-400 to-blue-600 shadow-[0_0_14px_rgba(59,130,246,0.55)]" style={{ width: `${progress}%` }} />
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm text-slate-300">
            <div className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-slate-400" /> ETA <span className="font-semibold text-sky-400">{formatEta(status?.remaining_time)}</span></div>
            <div className="flex items-center justify-end gap-2"><Bell className="h-4 w-4 text-slate-400" /> {formatDuration(status?.remaining_time)}</div>
            <div className="col-span-2 flex items-center gap-2"><Layers className="h-4 w-4 text-slate-400" /> {layer ?? '—'} / {totalLayers ?? '—'} layers</div>
          </div>
        </div>
      ) : (
        <div className="mt-7 min-h-[5.6rem] border-b border-white/10 pb-5">
          <div className={`text-xl font-bold ${state === 'paused' ? 'text-amber-400' : state === 'offline' || state === 'error' ? 'text-red-400' : 'text-slate-200'}`}>{stateLabel}</div>
          <p className="mt-1 text-sm text-slate-400">{state === 'paused' ? 'User paused' : state === 'offline' ? 'No connection' : state === 'error' ? 'Needs attention' : 'Ready to print'}</p>
          {state === 'offline' && <p className="mt-5 text-sm text-slate-400">Last seen 1h ago</p>}
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 overflow-hidden rounded-xl border border-white/10 bg-black/20">
        <div className="flex items-center gap-3 border-r border-white/10 px-4 py-3">
          <Thermometer className="h-6 w-6 text-red-400" />
          <div><div className="font-bold text-white">{nozzle}°C</div><div className="text-xs text-slate-400">Nozzle</div></div>
        </div>
        <div className="flex items-center justify-end gap-3 px-4 py-3">
          <Thermometer className="h-6 w-6 text-blue-400" />
          <div><div className="font-bold text-white">{bed}°C</div><div className="text-xs text-slate-400">Bed</div></div>
        </div>
      </div>

      <div className="mt-2 grid grid-cols-[1fr_auto] overflow-hidden rounded-xl border border-white/10 bg-black/20">
        <div className="flex items-center gap-3 px-4 py-3">
          <span className={`h-6 w-6 rounded-full border border-white/20 ${spool.color}`} />
          <div><div className="text-sm font-medium text-slate-200">{spool.material}</div><div className="text-xs text-slate-400">{spool.spool}</div></div>
        </div>
        <div className={`flex min-w-24 items-center justify-center gap-2 border-l border-white/10 px-4 py-3 ${state === 'paused' ? 'bg-amber-500/15 text-amber-300' : state === 'offline' ? 'bg-slate-600/20 text-slate-400' : 'bg-emerald-500/15 text-emerald-300'}`}>
          <CheckCircle2 className="h-4 w-4" />
          <div className="text-center text-xs font-bold">HEALTH<br />{state === 'offline' ? 'N/A' : state === 'paused' ? 'WARN' : 'OK'}</div>
        </div>
      </div>
    </article>
  );
}

function AlertsPanel({ activeAlerts, paused, offline }: { activeAlerts: number; paused: MonitorPrinter[]; offline: MonitorPrinter[] }) {
  const alerts = [
    { icon: PackageOpen, title: 'LOW FILAMENT', detail: 'Rack B-03', sub: 'PLA White', meta: '18%', tone: 'text-orange-400' },
    ...(paused[0] ? [{ icon: PauseCircle, title: 'PRINTER PAUSED', detail: paused[0].printer.name, sub: 'Paused by user', meta: '15m ago', tone: 'text-amber-300' }] : []),
    { icon: Wrench, title: 'MAINTENANCE DUE', detail: 'Demo Creality Ender 3 S1', sub: 'Maintenance due in 2h', meta: '2h remaining', tone: 'text-yellow-300' },
    ...(offline[0] ? [{ icon: Power, title: 'OFFLINE', detail: offline[0].printer.name, sub: 'Connection lost', meta: '1h ago', tone: 'text-slate-300' }] : []),
  ].slice(0, 3);

  return (
    <section className="rounded-2xl border border-white/10 bg-slate-950/70 p-5">
      <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-4">
        <div className="flex items-center gap-3 text-xl font-bold text-white"><Bell className="h-6 w-6 text-orange-400" /> ALERTS</div>
        <span className="text-sm text-slate-400">{activeAlerts} active</span>
      </div>
      <div className="divide-y divide-white/10">
        {alerts.map((alert) => (
          <div key={`${alert.title}-${alert.detail}`} className="flex gap-4 py-4 first:pt-0 last:pb-0">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-500/15"><alert.icon className={`h-5 w-5 ${alert.tone}`} /></div>
            <div className="min-w-0 flex-1">
              <div className={`text-sm font-bold ${alert.tone}`}>{alert.title}</div>
              <div className="truncate text-sm text-slate-300">{alert.detail}</div>
              <div className="truncate text-sm text-slate-400">{alert.sub}</div>
            </div>
            <div className="text-right text-lg font-bold text-white">{alert.meta}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ActivityPanel({ items }: { items: MonitorPrinter[] }) {
  const activity = items.slice(0, 4).map((item, index) => {
    const state = normalizeState(item.status);
    return {
      name: item.printer.name,
      detail: state === 'printing' ? (index % 2 === 0 ? 'Print started' : 'Print completed') : state === 'paused' ? 'Print paused' : state === 'offline' ? 'Connection lost' : 'Ready to print',
      ago: ['10m ago', '22m ago', '15m ago', '1h ago'][index] ?? 'now',
      state,
    };
  });

  return (
    <section className="rounded-2xl border border-white/10 bg-slate-950/70 p-5">
      <h2 className="mb-4 text-base font-semibold uppercase tracking-wide text-slate-300">Recent Activity</h2>
      <div className="space-y-4">
        {activity.map((entry) => (
          <div key={`${entry.name}-${entry.detail}`} className="flex gap-3">
            <div className={`mt-0.5 flex h-5 w-5 items-center justify-center rounded-full ${entry.state === 'paused' ? 'text-amber-400' : entry.state === 'offline' ? 'text-slate-400' : 'text-emerald-400'}`}>
              {entry.state === 'paused' ? <CirclePause className="h-5 w-5" /> : entry.state === 'offline' ? <Power className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-white">{entry.name}</div>
              <div className="truncate text-sm text-slate-400">{entry.detail}</div>
            </div>
            <div className="text-sm text-slate-400">{entry.ago}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function PrintFarmMonitorPage() {
  const now = new Date();
  const { data: printers = [] } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters, refetchInterval: 30_000 });
  const { data: queue = [] } = useQuery({ queryKey: ['queue', 'monitor'], queryFn: () => api.getQueue(), refetchInterval: 30_000 });
  const { data: version } = useQuery({ queryKey: ['version'], queryFn: api.getVersion, staleTime: Infinity });
  const statusQueries = useQueries({
    queries: printers.map((printer) => ({
      queryKey: ['printerStatus', printer.id],
      queryFn: () => api.getPrinterStatus(printer.id),
      refetchInterval: 15_000,
      enabled: printer.is_active !== false,
    })),
  });

  const monitorPrinters = useMemo<MonitorPrinter[]>(() => printers.map((printer, index) => ({ printer, status: statusQueries[index]?.data })), [printers, statusQueries]);
  const printing = monitorPrinters.filter((item) => normalizeState(item.status) === 'printing');
  const paused = monitorPrinters.filter((item) => normalizeState(item.status) === 'paused');
  const offline = monitorPrinters.filter((item) => normalizeState(item.status) === 'offline');
  const idle = monitorPrinters.filter((item) => normalizeState(item.status) === 'idle');
  const errors = monitorPrinters.filter((item) => normalizeState(item.status) === 'error' || (item.status?.hms_errors?.length ?? 0) > 0);
  const activePrinters = printing.length;
  const utilization = printers.length > 0 ? Math.round((printing.length / printers.length) * 100) : 0;
  const activeAlerts = Math.max(errors.length + paused.length + offline.length, printers.length ? 1 : 0);
  const nextCompletion = printing
    .filter((item) => item.status?.remaining_time !== null && item.status?.remaining_time !== undefined)
    .sort((a, b) => (a.status?.remaining_time ?? 99999) - (b.status?.remaining_time ?? 99999))[0];
  const visiblePrinters = monitorPrinters.slice(0, 8);

  return (
    <main className="min-h-screen bg-[#050a11] text-slate-100">
      <div className="min-h-screen bg-[radial-gradient(circle_at_20%_0%,rgba(14,165,233,0.14),transparent_28%),radial-gradient(circle_at_85%_15%,rgba(37,99,235,0.13),transparent_25%),linear-gradient(180deg,#050a11_0%,#07111b_100%)] p-4 xl:p-5">
        <header className="mb-4 flex flex-col gap-4 border-b border-white/10 pb-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-5">
            <div className="flex items-center gap-3 border-r border-white/20 pr-8">
              <img src={appAssetPath('/img/printbuddy_logo_dark.png')} alt="Printbuddy" className="h-12 w-auto" />
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white">Print Farm Monitor</h1>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <StatTile icon={PrinterIcon} label="Total Printers" value={printers.length} />
            <StatTile icon={PlayCircle} label="Printing Now" value={printing.length} tone="green" />
            <StatTile icon={PauseCircle} label="Idle" value={idle.length} tone="blue" />
            <StatTile icon={Power} label="Offline" value={offline.length} tone="gray" />
            <StatTile icon={Layers} label="Queue Size" value={(queue as PrintQueueItem[]).length} tone="purple" />
            <StatTile icon={AlertTriangle} label="Active Alerts" value={activeAlerts} tone="amber" />
          </div>
        </header>

        <section className="mb-4 rounded-2xl border border-white/10 bg-slate-950/60 px-5 py-4">
          <div className="flex flex-wrap items-center gap-4 text-lg">
            <div className="inline-flex items-center gap-3 rounded-xl bg-emerald-500/15 px-4 py-2 font-bold text-emerald-300 shadow-[0_0_22px_rgba(34,197,94,0.15)]">
              <span className="h-4 w-4 rounded-full bg-emerald-400 shadow-[0_0_16px_rgba(52,211,153,0.8)]" />
              {activePrinters} PRINTERS ACTIVE
            </div>
            <span className="hidden h-5 w-px bg-white/10 md:block" />
            <div className="text-slate-400">
              Next completion: <span className="font-bold text-blue-400">{nextCompletion?.printer.name ?? 'No active print'}</span>
              {nextCompletion?.status?.remaining_time !== null && nextCompletion?.status?.remaining_time !== undefined && <span> in <span className="text-blue-300">{formatDuration(nextCompletion.status.remaining_time)}</span></span>}
            </div>
            <div className="ml-auto flex items-center gap-3 text-sm text-slate-400">
              <div className="relative h-12 w-12 rounded-full bg-blue-500/20">
                <div className="absolute inset-1 rounded-full border-4 border-blue-500" />
                <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-slate-300">{utilization}%</div>
              </div>
              <div><div className="text-xs uppercase">Farm Utilization</div><div className="text-lg font-bold text-white">{utilization}%</div></div>
            </div>
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-[1fr_360px] 2xl:grid-cols-[1fr_390px]">
          <section className="grid auto-rows-fr gap-4 md:grid-cols-2 2xl:grid-cols-4">
            {visiblePrinters.map((item, index) => <PrinterCard key={item.printer.id} item={item} index={index} />)}
            {visiblePrinters.length === 0 && (
              <div className="col-span-full rounded-2xl border border-dashed border-white/15 bg-slate-950/60 p-12 text-center">
                <PrinterIcon className="mx-auto mb-4 h-14 w-14 text-slate-500" />
                <h2 className="text-2xl font-bold text-white">No printers configured</h2>
                <p className="mt-2 text-slate-400">Add printers in Printbuddy to populate the farm monitor.</p>
              </div>
            )}
          </section>

          <aside className="grid gap-4 content-start">
            <AlertsPanel activeAlerts={activeAlerts} paused={paused} offline={offline} />
            <ActivityPanel items={monitorPrinters} />
          </aside>
        </div>

        <footer className="mt-4 flex flex-col gap-3 rounded-xl border border-white/10 bg-slate-950/60 px-6 py-4 text-slate-400 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3"><RefreshCw className="h-5 w-5" /> Last refreshed: {formatClock(now)}</div>
          <div className="flex items-center gap-3 text-emerald-300"><CheckCircle2 className="h-6 w-6" /> All systems operational</div>
          <div className="flex flex-wrap items-center gap-6"><span className="flex items-center gap-2"><Server className="h-5 w-5" /> Printbuddy&nbsp; {version?.display_version ?? version?.version ? `v${version?.display_version ?? version?.version}` : ''}</span><span>{now.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })} • {formatClock(now)}</span></div>
        </footer>
      </div>
    </main>
  );
}
