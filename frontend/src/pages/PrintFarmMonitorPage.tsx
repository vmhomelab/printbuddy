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
import {
  api,
  type InventorySpool,
  type MaintenanceStatus,
  type PrintQueueItem,
  type Printer,
  type PrinterMaintenanceOverview,
  type PrinterStatus,
  type SpoolAssignment,
} from '../api/client';
import { getPrinterImage } from '../utils/printer';
import { appAssetPath } from '../utils/assetPaths';
import { useTheme } from '../contexts/ThemeContext';

interface MonitorPrinter {
  printer: Printer;
  status?: PrinterStatus;
}

type NormalizedState = 'printing' | 'idle' | 'paused' | 'stopped' | 'offline' | 'error';

type SpoolmanSlotAssignmentRow = {
  printer_id: number;
  printer_name: string | null;
  ams_id: number;
  tray_id: number;
  spoolman_spool_id: number;
  ams_label: string | null;
};

interface LoadedFilamentInfo {
  material: string;
  detail: string;
  color?: string | null;
  remainingPct?: number | null;
}

interface MonitorAlert {
  icon: typeof AlertTriangle;
  title: string;
  detail: string;
  sub: string;
  meta: string;
  tone: string;
}

interface MonitorThemeClasses {
  page: string;
  backdrop: string;
  panel: string;
  panelSoft: string;
  card: string;
  text: string;
  muted: string;
  subtle: string;
  border: string;
  divider: string;
  imageBox: string;
  footer: string;
  ringInner: string;
  logoPath: string;
}

const DEFAULT_REFRESH_SECONDS = 15;

function getMonitorTheme(mode: 'dark' | 'light'): MonitorThemeClasses {
  if (mode === 'light') {
    return {
      page: 'bg-slate-100 text-slate-950',
      backdrop: 'bg-[radial-gradient(circle_at_20%_0%,rgba(14,165,233,0.16),transparent_30%),radial-gradient(circle_at_85%_15%,rgba(59,130,246,0.13),transparent_26%),linear-gradient(180deg,#f8fafc_0%,#e2e8f0_100%)]',
      panel: 'border-slate-300/80 bg-white/80 shadow-[0_20px_45px_rgba(15,23,42,0.10)]',
      panelSoft: 'border-slate-300/80 bg-slate-50/85',
      card: 'border-slate-300/80 bg-white/85 shadow-[inset_0_1px_0_rgba(255,255,255,0.85),0_20px_45px_rgba(15,23,42,0.12)]',
      text: 'text-slate-950',
      muted: 'text-slate-600',
      subtle: 'text-slate-500',
      border: 'border-slate-300/80',
      divider: 'border-slate-300/70',
      imageBox: 'border-slate-300 bg-slate-100/80',
      footer: 'border-slate-300/80 bg-white/80 text-slate-600',
      ringInner: 'bg-slate-50',
      logoPath: '/img/printbuddy_logo_light.png',
    };
  }
  return {
    page: 'bg-[#050a11] text-slate-100',
    backdrop: 'bg-[radial-gradient(circle_at_20%_0%,rgba(14,165,233,0.14),transparent_28%),radial-gradient(circle_at_85%_15%,rgba(37,99,235,0.13),transparent_25%),linear-gradient(180deg,#050a11_0%,#07111b_100%)]',
    panel: 'border-white/10 bg-slate-950/70 shadow-[0_20px_45px_rgba(0,0,0,0.25)]',
    panelSoft: 'border-white/10 bg-slate-950/60',
    card: 'border-white/10 bg-slate-950/70 shadow-[inset_0_1px_0_rgba(255,255,255,0.04),0_20px_45px_rgba(0,0,0,0.25)]',
    text: 'text-white',
    muted: 'text-slate-400',
    subtle: 'text-slate-500',
    border: 'border-white/10',
    divider: 'border-white/10',
    imageBox: 'border-white/10 bg-black/30',
    footer: 'border-white/10 bg-slate-950/60 text-slate-400',
    ringInner: 'bg-[#07111b]',
    logoPath: '/img/printbuddy_logo_dark.png',
  };
}


function normalizeRefreshSeconds(value: number | null | undefined): number {
  if (!Number.isFinite(value ?? NaN)) return DEFAULT_REFRESH_SECONDS;
  return Math.min(300, Math.max(5, Math.round(value!)));
}

function normalizeState(status?: PrinterStatus): NormalizedState {
  if (!status || !status.connected) return 'offline';
  const state = (status.state ?? '').toLowerCase();
  if (state.includes('pause')) return 'paused';
  if (state.includes('stop') || state.includes('cancel')) return 'stopped';
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

function getJobName(item: MonitorPrinter): string | null {
  return item.status?.current_print || item.status?.subtask_name || item.status?.gcode_file || null;
}

function spoolLabel(spool: InventorySpool): string {
  return [spool.brand, spool.material, spool.subtype, spool.color_name].filter(Boolean).join(' ');
}

function spoolRemainingPct(spool: InventorySpool): number | null {
  if (!spool.label_weight || spool.label_weight <= 0) return null;
  const remaining = Math.max(0, spool.label_weight - (spool.weight_used ?? 0));
  return Math.round((remaining / spool.label_weight) * 100);
}

function normalizeSpoolColor(color: string | null | undefined): string | null {
  if (!color) return null;
  const trimmed = color.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith('#') || trimmed.startsWith('rgb') || trimmed.startsWith('hsl')) return trimmed;
  if (/^[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(trimmed)) return `#${trimmed.slice(0, 6)}`;
  return trimmed;
}

function displaySpoolColor(color: string | null | undefined): string | null {
  const normalized = normalizeSpoolColor(color);
  return normalized?.startsWith('#') ? normalized.toUpperCase() : normalized;
}

function getLoadedFilamentInfo(
  item: MonitorPrinter,
  localAssignments: SpoolAssignment[],
  spoolmanSpools: InventorySpool[],
  spoolmanSlotAssignments: SpoolmanSlotAssignmentRow[],
): LoadedFilamentInfo | null {
  const { printer, status } = item;

  const loadedLocal = localAssignments.find((assignment) => assignment.printer_id === printer.id && assignment.ams_id === -1 && assignment.tray_id === 0)?.spool;
  if (loadedLocal) {
    return {
      material: spoolLabel(loadedLocal),
      detail: 'Loaded spool',
      color: loadedLocal.rgba,
      remainingPct: spoolRemainingPct(loadedLocal),
    };
  }

  const loadedSpoolmanAssignment = spoolmanSlotAssignments.find((assignment) => assignment.printer_id === printer.id && assignment.ams_id === 255 && assignment.tray_id === 0);
  const loadedSpoolman = loadedSpoolmanAssignment ? spoolmanSpools.find((spool) => spool.id === loadedSpoolmanAssignment.spoolman_spool_id) : undefined;
  if (loadedSpoolman) {
    return {
      material: spoolLabel(loadedSpoolman),
      detail: 'Loaded spool',
      color: loadedSpoolman.rgba,
      remainingPct: spoolRemainingPct(loadedSpoolman),
    };
  }

  const virtualTray = status?.vt_tray?.find((tray) => tray.tray_type || tray.tray_sub_brands || tray.tray_color);
  if (virtualTray) {
    return {
      material: [virtualTray.tray_type, virtualTray.tray_sub_brands].filter(Boolean).join(' ') || 'External filament',
      detail: 'External spool',
      color: virtualTray.tray_color,
      remainingPct: typeof virtualTray.remain === 'number' ? virtualTray.remain : null,
    };
  }

  const amsTray = status?.ams
    ?.flatMap((ams) => ams.tray.map((tray) => ({ amsId: ams.id, tray })))
    .find(({ tray }) => tray.tray_type || tray.tray_sub_brands || tray.tray_color);
  if (amsTray) {
    return {
      material: [amsTray.tray.tray_type, amsTray.tray.tray_sub_brands].filter(Boolean).join(' ') || `AMS ${amsTray.amsId} tray ${amsTray.tray.id}`,
      detail: `AMS ${amsTray.amsId} tray ${amsTray.tray.id}`,
      color: amsTray.tray.tray_color,
      remainingPct: typeof amsTray.tray.remain === 'number' ? amsTray.tray.remain : null,
    };
  }

  return null;
}

function getLowSpoolAlerts(spools: InventorySpool[], defaultThreshold: number): MonitorAlert[] {
  return spools
    .filter((spool) => !spool.archived_at)
    .map((spool) => {
      const remainingPct = spoolRemainingPct(spool);
      const threshold = spool.low_stock_threshold_pct ?? defaultThreshold;
      return { spool, remainingPct, threshold };
    })
    .filter((entry): entry is { spool: InventorySpool; remainingPct: number; threshold: number } => entry.remainingPct !== null && entry.remainingPct <= entry.threshold)
    .sort((a, b) => a.remainingPct - b.remainingPct)
    .slice(0, 4)
    .map(({ spool, remainingPct }) => ({
      icon: PackageOpen,
      title: 'LOW FILAMENT',
      detail: spoolLabel(spool),
      sub: spool.storage_location || spool.category || 'Inventory spool',
      meta: `${remainingPct}%`,
      tone: 'text-orange-400',
    }));
}

function getMaintenanceAlerts(overview: PrinterMaintenanceOverview[]): MonitorAlert[] {
  return overview
    .flatMap((printer) => printer.maintenance_items.map((item) => ({ printer, item })))
    .filter(({ item }) => item.enabled && (item.is_due || item.is_warning))
    .sort((a, b) => Number(b.item.is_due) - Number(a.item.is_due) || a.item.hours_until_due - b.item.hours_until_due)
    .slice(0, 4)
    .map(({ printer, item }) => ({
      icon: Wrench,
      title: item.is_due ? 'MAINTENANCE DUE' : 'MAINTENANCE SOON',
      detail: printer.printer_name,
      sub: item.maintenance_type_name,
      meta: formatMaintenanceMeta(item),
      tone: item.is_due ? 'text-yellow-300' : 'text-amber-300',
    }));
}

function formatMaintenanceMeta(item: MaintenanceStatus): string {
  if (item.interval_type === 'days') {
    if (item.days_until_due === null || item.days_until_due === undefined) return item.is_due ? 'due' : 'soon';
    if (item.days_until_due <= 0) return 'due';
    return `${Math.round(item.days_until_due)}d`;
  }
  if (item.hours_until_due <= 0) return 'due';
  return `${Math.round(item.hours_until_due)}h`;
}

function getPrinterAlerts(items: MonitorPrinter[]): MonitorAlert[] {
  return items.flatMap((item) => {
    const state = normalizeState(item.status);
    if (state === 'offline') {
      return [{
        icon: Power,
        title: 'PRINTER OFFLINE',
        detail: item.printer.name,
        sub: 'Connection lost',
        meta: 'now',
        tone: 'text-slate-300',
      }];
    }
    if (state === 'paused') {
      return [{
        icon: PauseCircle,
        title: 'PRINT PAUSED',
        detail: item.printer.name,
        sub: getJobName(item) || 'Paused by printer state',
        meta: formatDuration(item.status?.remaining_time),
        tone: 'text-amber-300',
      }];
    }
    if (state === 'stopped') {
      return [{
        icon: CirclePause,
        title: 'PRINT STOPPED',
        detail: item.printer.name,
        sub: getJobName(item) || 'Stopped by printer state',
        meta: 'stopped',
        tone: 'text-orange-300',
      }];
    }
    if (state === 'error' || (item.status?.hms_errors?.length ?? 0) > 0) {
      return [{
        icon: AlertTriangle,
        title: 'PRINTER ERROR',
        detail: item.printer.name,
        sub: `${item.status?.hms_errors?.length ?? 0} active printer error${(item.status?.hms_errors?.length ?? 0) === 1 ? '' : 's'}`,
        meta: 'error',
        tone: 'text-red-300',
      }];
    }
    return [];
  });
}

function StatTile({ icon: Icon, label, value, theme, tone = 'blue', suffix }: { icon: typeof PrinterIcon; label: string; value: string | number; theme: MonitorThemeClasses; tone?: 'blue' | 'green' | 'gray' | 'purple' | 'amber'; suffix?: string }) {
  const toneClasses = {
    blue: 'bg-blue-500/15 text-blue-400',
    green: 'bg-emerald-500/15 text-emerald-400',
    gray: 'bg-slate-500/20 text-slate-300',
    purple: 'bg-purple-500/15 text-purple-300',
    amber: 'bg-amber-500/15 text-amber-300',
  };

  return (
    <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${theme.panel}`}>
      <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${toneClasses[tone]}`}>
        <Icon className="h-6 w-6" />
      </div>
      <div className="min-w-0">
        <div className={`text-[0.65rem] font-semibold uppercase tracking-wide ${theme.muted}`}>{label}</div>
        <div className={`flex items-baseline gap-1 text-2xl font-bold ${theme.text}`}>
          {value}{suffix && <span className={`text-sm font-semibold ${theme.muted}`}>{suffix}</span>}
        </div>
      </div>
    </div>
  );
}

function PrinterCard({ item, loadedFilament, theme }: { item: MonitorPrinter; loadedFilament: LoadedFilamentInfo | null; theme: MonitorThemeClasses }) {
  const { printer, status } = item;
  const state = normalizeState(status);
  const progress = status?.progress === null || status?.progress === undefined ? null : Math.min(100, Math.max(0, Math.round(status.progress)));
  const nozzle = status?.temperatures?.nozzle === null || status?.temperatures?.nozzle === undefined ? null : Math.round(status.temperatures.nozzle);
  const bed = status?.temperatures?.bed === null || status?.temperatures?.bed === undefined ? null : Math.round(status.temperatures.bed);
  const layer = status?.layer_num ?? null;
  const totalLayers = status?.total_layers ?? null;
  const jobName = getJobName(item);

  const stateClasses = {
    printing: 'bg-emerald-500/15 text-emerald-300 shadow-emerald-500/20',
    idle: 'bg-blue-500/15 text-blue-300 shadow-blue-500/20',
    paused: 'bg-amber-500/15 text-amber-300 shadow-amber-500/20',
    stopped: 'bg-orange-500/15 text-orange-300 shadow-orange-500/20',
    offline: 'bg-slate-500/15 text-slate-300 shadow-slate-500/20',
    error: 'bg-red-500/15 text-red-300 shadow-red-500/20',
  };
  const stateLabel = state === 'printing' ? 'PRINTING' : state === 'paused' ? 'PAUSED' : state === 'stopped' ? 'STOPPED' : state === 'offline' ? 'OFFLINE' : state === 'error' ? 'ERROR' : 'IDLE';

  return (
    <article className={`rounded-2xl border p-5 ${theme.card}`}>
      <div className="flex gap-4">
        <div className={`flex h-28 w-32 shrink-0 items-center justify-center overflow-hidden rounded-xl border p-2 ${theme.imageBox}`}>
          {state === 'offline' ? <TriangleAlert className="h-12 w-12 text-red-400" /> : <img src={getPrinterImage(printer.model)} alt="" className="max-h-full max-w-full object-contain" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className={`mb-3 inline-flex items-center gap-2 rounded-lg px-3 py-1 text-xs font-bold shadow-lg ${stateClasses[state]}`}>
            <span className={`h-2 w-2 rounded-full ${state === 'printing' ? 'bg-emerald-400' : state === 'paused' ? 'bg-amber-400' : state === 'stopped' ? 'bg-orange-400' : state === 'offline' ? 'bg-slate-400' : state === 'error' ? 'bg-red-400' : 'bg-blue-400'}`} />
            {stateLabel}
          </div>
          <h2 className={`truncate text-lg font-bold ${theme.text}`}>{printer.name}</h2>
          <p className={`truncate text-sm ${theme.muted}`}>{printer.model || printer.provider || 'Printer'}</p>
          {printer.location && <p className={`truncate text-sm ${theme.muted}`}>{printer.location}</p>}
        </div>
      </div>

      {state === 'printing' ? (
        <div className="mt-5 space-y-3">
          <div>
            <div className={`mb-1 text-[0.68rem] font-semibold uppercase ${theme.subtle}`}>Current job</div>
            <div className="flex items-end justify-between gap-3">
              <div className={`truncate font-semibold ${theme.text}`}>{jobName ?? 'Active print'}</div>
              <div className={`text-2xl font-bold ${theme.text}`}>{progress !== null ? `${progress}%` : '—'}</div>
            </div>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-slate-800">
            <div className="h-full rounded-full bg-gradient-to-r from-sky-400 to-blue-600 shadow-[0_0_14px_rgba(59,130,246,0.55)]" style={{ width: `${progress ?? 0}%` }} />
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm text-slate-300">
            <div className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-slate-400" /> ETA <span className="font-semibold text-sky-400">{formatEta(status?.remaining_time)}</span></div>
            <div className="flex items-center justify-end gap-2"><Bell className="h-4 w-4 text-slate-400" /> {formatDuration(status?.remaining_time)}</div>
            {(layer !== null || totalLayers !== null) && <div className="col-span-2 flex items-center gap-2"><Layers className="h-4 w-4 text-slate-400" /> {layer ?? '—'} / {totalLayers ?? '—'} layers</div>}
          </div>
        </div>
      ) : (
        <div className={`mt-7 min-h-[5.6rem] border-b pb-5 ${theme.divider}`}>
          <div className={`text-xl font-bold ${state === 'paused' ? 'text-amber-400' : state === 'stopped' ? 'text-orange-400' : state === 'offline' || state === 'error' ? 'text-red-400' : 'text-slate-200'}`}>{stateLabel}</div>
          <p className="mt-1 text-sm text-slate-400">{state === 'paused' ? 'Print paused' : state === 'stopped' ? 'Print stopped' : state === 'offline' ? 'No connection' : state === 'error' ? 'Needs attention' : 'Ready to print'}</p>
        </div>
      )}

      {(nozzle !== null || bed !== null) && (
        <div className={`mt-4 grid grid-cols-2 overflow-hidden rounded-xl border ${theme.divider} ${theme.panelSoft}`}>
          <div className={`flex items-center gap-3 border-r px-4 py-3 ${theme.divider}`}>
            <Thermometer className="h-6 w-6 text-red-400" />
            <div><div className={`font-bold ${theme.text}`}>{nozzle !== null ? `${nozzle}°C` : '—'}</div><div className={`text-xs ${theme.muted}`}>Nozzle</div></div>
          </div>
          <div className="flex items-center justify-end gap-3 px-4 py-3">
            <Thermometer className="h-6 w-6 text-blue-400" />
            <div><div className={`font-bold ${theme.text}`}>{bed !== null ? `${bed}°C` : '—'}</div><div className={`text-xs ${theme.muted}`}>Bed</div></div>
          </div>
        </div>
      )}

      {loadedFilament && (
        <div className={`mt-2 grid grid-cols-[1fr_auto] overflow-hidden rounded-xl border ${theme.divider} ${theme.panelSoft}`}>
          <div className="flex items-center gap-3 px-4 py-3">
            <span className="h-9 w-9 rounded-xl border border-white/25 shadow-[inset_0_0_0_1px_rgba(0,0,0,0.25)]" style={{ backgroundColor: normalizeSpoolColor(loadedFilament.color) || '#64748b' }} />
            <div>
              <div className={`text-sm font-medium ${theme.text}`}>{loadedFilament.material}</div>
              <div className={`text-xs ${theme.muted}`}>{loadedFilament.detail}{displaySpoolColor(loadedFilament.color) ? ` · ${displaySpoolColor(loadedFilament.color)}` : ''}</div>
            </div>
          </div>
          {loadedFilament.remainingPct !== null && loadedFilament.remainingPct !== undefined && (
            <div className={`flex min-w-24 items-center justify-center border-l px-4 py-3 text-center text-xs font-bold ${theme.divider} ${theme.muted}`}>
              {loadedFilament.remainingPct}%<br />LEFT
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function AlertsPanel({ alerts, theme }: { alerts: MonitorAlert[]; theme: MonitorThemeClasses }) {
  return (
    <section className={`rounded-2xl border p-5 ${theme.card}`}>
      <div className={`mb-4 flex items-center justify-between border-b pb-4 ${theme.divider}`}>
        <div className={`flex items-center gap-3 text-xl font-bold ${theme.text}`}><Bell className="h-6 w-6 text-orange-400" /> ALERTS</div>
        <span className={`text-sm ${theme.muted}`}>{alerts.length} active</span>
      </div>
      {alerts.length > 0 ? (
        <div className="divide-y divide-white/10">
          {alerts.slice(0, 5).map((alert) => (
            <div key={`${alert.title}-${alert.detail}-${alert.sub}`} className="flex gap-4 py-4 first:pt-0 last:pb-0">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-500/15"><alert.icon className={`h-5 w-5 ${alert.tone}`} /></div>
              <div className="min-w-0 flex-1">
                <div className={`text-sm font-bold ${alert.tone}`}>{alert.title}</div>
                <div className={`truncate text-sm ${theme.text}`}>{alert.detail}</div>
                <div className={`truncate text-sm ${theme.muted}`}>{alert.sub}</div>
              </div>
              <div className={`text-right text-lg font-bold ${theme.text}`}>{alert.meta}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className={`py-8 text-center text-sm ${theme.muted}`}>No active alerts from printer, inventory, or maintenance data.</div>
      )}
    </section>
  );
}

function ActivityPanel({ items, theme }: { items: MonitorPrinter[]; theme: MonitorThemeClasses }) {
  const activity = items
    .filter((item) => ['printing', 'paused', 'stopped', 'offline', 'error'].includes(normalizeState(item.status)))
    .slice(0, 4)
    .map((item) => {
      const state = normalizeState(item.status);
      return {
        name: item.printer.name,
        detail: state === 'printing' ? 'Printing' : state === 'paused' ? 'Print paused' : state === 'stopped' ? 'Print stopped' : state === 'offline' ? 'Connection lost' : 'Printer error',
        state,
      };
    });

  return (
    <section className={`rounded-2xl border p-5 ${theme.card}`}>
      <h2 className={`mb-4 text-base font-semibold uppercase tracking-wide ${theme.muted}`}>Recent Activity</h2>
      {activity.length > 0 ? (
        <div className="space-y-4">
          {activity.map((entry) => (
            <div key={`${entry.name}-${entry.detail}`} className="flex gap-3">
              <div className={`mt-0.5 flex h-5 w-5 items-center justify-center rounded-full ${entry.state === 'paused' || entry.state === 'stopped' ? 'text-amber-400' : entry.state === 'offline' ? 'text-slate-400' : entry.state === 'error' ? 'text-red-400' : 'text-emerald-400'}`}>
                {entry.state === 'paused' || entry.state === 'stopped' ? <CirclePause className="h-5 w-5" /> : entry.state === 'offline' ? <Power className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className={`truncate text-sm font-medium ${theme.text}`}>{entry.name}</div>
                <div className={`truncate text-sm ${theme.muted}`}>{entry.detail}</div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className={`py-8 text-center text-sm ${theme.muted}`}>No active printer events.</div>
      )}
    </section>
  );
}

export function PrintFarmMonitorPage() {
  const now = new Date();
  const { mode } = useTheme();
  const theme = useMemo(() => getMonitorTheme(mode), [mode]);
  const { data: uiPreferences } = useQuery({ queryKey: ['ui-preferences'], queryFn: api.getUiPreferences, staleTime: 30_000 });
  const refreshSeconds = normalizeRefreshSeconds(uiPreferences?.print_farm_monitor_refresh_interval);
  const refreshMs = refreshSeconds * 1000;
  const { data: printers = [] } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters, refetchInterval: refreshMs });
  const { data: queue = [] } = useQuery({ queryKey: ['queue', 'monitor'], queryFn: () => api.getQueue(), refetchInterval: refreshMs });
  const { data: version } = useQuery({ queryKey: ['version'], queryFn: api.getVersion, staleTime: Infinity });
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.getSettings, staleTime: 60_000 });
  const { data: spoolmanSettings } = useQuery({ queryKey: ['settings', 'spoolman', 'monitor'], queryFn: api.getSpoolmanSettings, staleTime: 60_000, retry: false });
  const { data: localAssignments = [] } = useQuery({ queryKey: ['inventory-assignments', 'monitor'], queryFn: () => api.getAssignments(), refetchInterval: refreshMs, retry: false });
  const { data: localSpools = [] } = useQuery({ queryKey: ['inventory-spools', 'monitor'], queryFn: () => api.getSpools(false), refetchInterval: refreshMs, retry: false });
  const spoolmanEnabled = spoolmanSettings?.spoolman_enabled === 'true';
  const { data: spoolmanSpools = [] } = useQuery({ queryKey: ['spoolman-inventory-spools', 'monitor'], queryFn: () => api.getSpoolmanInventorySpools(false), enabled: spoolmanEnabled, refetchInterval: refreshMs, retry: false });
  const { data: spoolmanSlotAssignments = [] } = useQuery({ queryKey: ['spoolman-slot-assignments', 'monitor'], queryFn: () => api.getSpoolmanSlotAssignments(), enabled: spoolmanEnabled, refetchInterval: refreshMs, retry: false });
  const { data: maintenanceOverview = [] } = useQuery({ queryKey: ['maintenance-overview', 'monitor'], queryFn: api.getMaintenanceOverview, refetchInterval: refreshMs, retry: false });
  const statusQueries = useQueries({
    queries: printers.map((printer) => ({
      queryKey: ['printerStatus', printer.id],
      queryFn: () => api.getPrinterStatus(printer.id),
      refetchInterval: refreshMs,
      enabled: printer.is_active !== false,
    })),
  });

  const monitorPrinters = useMemo<MonitorPrinter[]>(() => printers.map((printer, index) => ({ printer, status: statusQueries[index]?.data })), [printers, statusQueries]);
  const loadedFilaments = useMemo(() => new Map(monitorPrinters.map((item) => [item.printer.id, getLoadedFilamentInfo(item, localAssignments, spoolmanSpools, spoolmanSlotAssignments)])), [localAssignments, monitorPrinters, spoolmanSlotAssignments, spoolmanSpools]);
  const printing = monitorPrinters.filter((item) => normalizeState(item.status) === 'printing');
  const paused = monitorPrinters.filter((item) => normalizeState(item.status) === 'paused');
  const stopped = monitorPrinters.filter((item) => normalizeState(item.status) === 'stopped');
  const offline = monitorPrinters.filter((item) => normalizeState(item.status) === 'offline');
  const idle = monitorPrinters.filter((item) => normalizeState(item.status) === 'idle');
  const errors = monitorPrinters.filter((item) => normalizeState(item.status) === 'error' || (item.status?.hms_errors?.length ?? 0) > 0);
  const utilization = printers.length > 0 ? Math.round((printing.length / printers.length) * 100) : 0;
  const activeAlerts = useMemo(() => [
    ...getPrinterAlerts(monitorPrinters),
    ...getLowSpoolAlerts(spoolmanEnabled ? spoolmanSpools : localSpools, settings?.low_stock_threshold ?? 20),
    ...getMaintenanceAlerts(maintenanceOverview),
  ], [localSpools, maintenanceOverview, monitorPrinters, settings?.low_stock_threshold, spoolmanEnabled, spoolmanSpools]);
  const nextCompletion = printing
    .filter((item) => item.status?.remaining_time !== null && item.status?.remaining_time !== undefined)
    .sort((a, b) => (a.status?.remaining_time ?? 99999) - (b.status?.remaining_time ?? 99999))[0];
  const visiblePrinters = monitorPrinters.slice(0, 8);
  const utilizationStyle = { background: `conic-gradient(#3b82f6 ${utilization * 3.6}deg, rgba(30,41,59,0.95) 0deg)` };

  return (
    <main className={`min-h-screen ${theme.page}`} data-monitor-theme={mode}>
      <div className={`min-h-screen p-4 xl:p-5 ${theme.backdrop}`}>
        <header className={`mb-4 flex flex-col gap-4 border-b pb-4 xl:flex-row xl:items-center xl:justify-between ${theme.divider}`}>
          <div className="flex items-center gap-5">
            <div className={`flex items-center gap-3 border-r pr-8 ${theme.divider}`}>
              <img src={appAssetPath(theme.logoPath)} alt="Printbuddy" className="h-12 w-auto" />
            </div>
            <h1 className={`text-3xl font-bold tracking-tight ${theme.text}`}>Print Farm Monitor</h1>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <StatTile icon={PrinterIcon} label="Total Printers" value={printers.length} theme={theme} />
            <StatTile icon={PlayCircle} label="Printing Now" value={printing.length} tone="green" theme={theme} />
            <StatTile icon={PauseCircle} label="Idle" value={idle.length} tone="blue" theme={theme} />
            <StatTile icon={Power} label="Offline" value={offline.length} tone="gray" theme={theme} />
            <StatTile icon={Layers} label="Queue Size" value={(queue as PrintQueueItem[]).length} tone="purple" theme={theme} />
            <StatTile icon={AlertTriangle} label="Active Alerts" value={activeAlerts.length} tone="amber" theme={theme} />
          </div>
        </header>

        <section className={`mb-4 rounded-2xl border px-5 py-4 ${theme.panelSoft}`}>
          <div className="flex flex-wrap items-center gap-4 text-lg">
            <div className="inline-flex items-center gap-3 rounded-xl bg-emerald-500/15 px-4 py-2 font-bold text-emerald-300 shadow-[0_0_22px_rgba(34,197,94,0.15)]">
              <span className="h-4 w-4 rounded-full bg-emerald-400 shadow-[0_0_16px_rgba(52,211,153,0.8)]" />
              {printing.length} PRINTERS ACTIVE
            </div>
            <span className={`hidden h-5 w-px md:block ${mode === 'light' ? 'bg-slate-300' : 'bg-white/10'}`} />
            <div className={theme.muted}>
              Next completion: <span className="font-bold text-blue-400">{nextCompletion?.printer.name ?? 'No active print'}</span>
              {nextCompletion?.status?.remaining_time !== null && nextCompletion?.status?.remaining_time !== undefined && <span> in <span className="text-blue-300">{formatDuration(nextCompletion.status.remaining_time)}</span></span>}
            </div>
            <div className={`ml-auto flex items-center gap-3 text-sm ${theme.muted}`}>
              <div className="relative h-12 w-12 rounded-full p-1" style={utilizationStyle} aria-label={`Farm utilization ${utilization}%`}>
                <div className={`h-full w-full rounded-full ${theme.ringInner}`} />
              </div>
              <div><div className="text-xs uppercase">Farm Utilization</div><div className={`text-2xl font-bold ${theme.text}`}>{utilization}%</div></div>
            </div>
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-[1fr_360px] 2xl:grid-cols-[1fr_390px]">
          <section className="grid auto-rows-fr gap-4 md:grid-cols-2 2xl:grid-cols-4">
            {visiblePrinters.map((item) => <PrinterCard key={item.printer.id} item={item} loadedFilament={loadedFilaments.get(item.printer.id) ?? null} theme={theme} />)}
            {visiblePrinters.length === 0 && (
              <div className={`col-span-full rounded-2xl border border-dashed p-12 text-center ${theme.panelSoft}`}>
                <PrinterIcon className={`mx-auto mb-4 h-14 w-14 ${theme.subtle}`} />
                <h2 className={`text-2xl font-bold ${theme.text}`}>No printers configured</h2>
                <p className={`mt-2 ${theme.muted}`}>Add printers in Printbuddy to populate the farm monitor.</p>
              </div>
            )}
          </section>

          <aside className="grid gap-4 content-start">
            <AlertsPanel alerts={activeAlerts} theme={theme} />
            <ActivityPanel items={[...printing, ...paused, ...stopped, ...offline, ...errors]} theme={theme} />
          </aside>
        </div>

        <footer className={`mt-4 flex flex-col gap-3 rounded-xl border px-6 py-4 md:flex-row md:items-center md:justify-between ${theme.footer}`}>
          <div className="flex items-center gap-3"><RefreshCw className="h-5 w-5" /> Last refreshed: {formatClock(now)} · every {refreshSeconds}s</div>
          <div className="flex items-center gap-3 text-emerald-300"><CheckCircle2 className="h-6 w-6" /> PrintBuddy is operational</div>
          <div className="flex flex-wrap items-center gap-6"><span className="flex items-center gap-2"><Server className="h-5 w-5" /> Printbuddy&nbsp; {version?.display_version ?? version?.version ? `v${version?.display_version ?? version?.version}` : ''}</span><span>{now.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })} • {formatClock(now)}</span></div>
        </footer>
      </div>
    </main>
  );
}
