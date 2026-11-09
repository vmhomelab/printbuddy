import { useState } from 'react';
import {
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Home,
  ChevronUp,
  ChevronDown,
  Save,
  Thermometer,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { Printer, PrinterStatus } from '../api/client';

type ToastType = 'success' | 'error' | 'warning' | 'info' | 'loading';

const XY_STEPS = [0.1, 1, 10, 25, 50, 100];
const Z_OFFSET_STEPS = [0.005, 0.01, 0.025, 0.05];

type ControlPanelStatus = Partial<PrinterStatus> & {
  temperatures?: PrinterStatus['temperatures'];
  position?: { x?: number; y?: number; z?: number } | null;
  z_offset?: number | null;
};

interface Props {
  printer: Printer;
  status?: ControlPanelStatus;
  showToast: (msg: string, type?: ToastType) => void;
}

export function KlipperControlPanel({ printer, status, showToast }: Props) {
  const { t } = useTranslation();
  const [xyStep, setXyStep] = useState(10);
  const [zOffsetStep, setZOffsetStep] = useState(0.01);
  const [extrudeLength, setExtrudeLength] = useState(10);
  const [extrudeSpeed, setExtrudeSpeed] = useState(5);
  const [nozzleInput, setNozzleInput] = useState('');
  const [bedInput, setBedInput] = useState('');
  // PrusaLink and OctoPrint have no Klipper-specific routes (z-offset, macros);
  // they use the provider-neutral jog/home/extrude endpoints.
  const usesGenericControls = printer.provider === 'prusalink' || printer.provider === 'octoprint';
  const [chamberInput, setChamberInput] = useState('');

  const onError = () =>
    showToast(t('printers.toast.failedToSendCommand', 'Command failed'), 'error');

  const moveMut = useMutation({
    mutationFn: ({ axis, distance }: { axis: 'x' | 'y' | 'z'; distance: number }) =>
      api.axisJog(printer.id, axis, distance),
    onError,
  });

  const homeMut = useMutation({
    mutationFn: (axes?: string[]) => {
      if (usesGenericControls) {
        const normalized = axes?.join('').toLowerCase() || 'all';
        const prusaAxes = normalized === 'xy' || normalized === 'x' || normalized === 'y' || normalized === 'z'
          ? normalized
          : 'all';
        return api.homeAxes(printer.id, prusaAxes);
      }
      return api.klipperHome(printer.id, axes);
    },
    onError,
  });

  const extrudeMut = useMutation({
    mutationFn: (length: number) => {
      const speed = extrudeSpeed * 60;
      return usesGenericControls
        ? api.extrude(printer.id, length, speed)
        : api.klipperExtrude(printer.id, length, speed);
    },
    onError,
  });

  const zOffsetMut = useMutation({
    mutationFn: ({ amount, save }: { amount: number; save?: boolean }) =>
      api.klipperZOffset(printer.id, amount, save ?? false),
    onError,
  });

  const nozzleMut = useMutation({
    mutationFn: (target: number) => api.setNozzleTemperature(printer.id, target),
    onSuccess: () => setNozzleInput(''),
    onError,
  });

  const bedMut = useMutation({
    mutationFn: (target: number) => api.setBedTemperature(printer.id, target),
    onSuccess: () => setBedInput(''),
    onError,
  });

  const chamberMut = useMutation({
    mutationFn: (target: number) => api.setChamberTemperature(printer.id, target),
    onSuccess: () => setChamberInput(''),
    onError,
  });

  const disableSteppersMut = useMutation({
    mutationFn: () => api.disableSteppers(printer.id),
    onError,
  });

  const pos: Record<string, number | undefined> = status?.position ?? {};
  const zOffset = status?.z_offset;
  // Providers that do not report a position/offset show a dash instead of a fake 0.00.
  const formatAxis = (value: number | undefined) => (typeof value === 'number' ? value.toFixed(2) : '—');
  const temps = status?.temperatures ?? {};
  const busy = moveMut.isPending || homeMut.isPending;
  const hasChamberHeater = status?.chamber_heater_supported === true;
  const chamberMax = Math.round(status?.chamber_temp_max ?? 100);
  const submitChamber = () => {
    if (chamberInput === '') return;
    const target = Number(chamberInput);
    if (!Number.isFinite(target) || target < 0 || target > chamberMax) {
      showToast(t('printers.klipper.chamberRange', { max: chamberMax, defaultValue: `Chamber target must be 0-${chamberMax}°C` }), 'error');
      return;
    }
    chamberMut.mutate(target);
  };

  const accentControlBtn =
    'flex items-center justify-center rounded bg-[var(--accent)] hover:bg-[var(--accent-light)] active:bg-[var(--accent-dark)] text-white shadow-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer select-none';
  const joyBtn = `${accentControlBtn} w-10 h-10`;
  const homeBtn =
    'flex items-center justify-center gap-0.5 px-1 h-10 min-w-[40px] rounded border border-[var(--accent)] bg-[var(--bg-tertiary)] hover:bg-[var(--accent)] hover:text-white text-[var(--accent)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer select-none text-xs font-bold';
  const secondaryControlBtn =
    'border border-[var(--accent)] bg-[var(--bg-primary)] hover:bg-[var(--accent)] hover:text-white text-[var(--accent)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer';
  const stepBtnClass = (active: boolean) =>
    `px-2 py-1 rounded text-xs font-mono transition-colors cursor-pointer select-none border ${
      active
        ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
        : 'bg-transparent text-[var(--text-secondary)] border-[var(--border-color)] hover:border-[var(--text-muted)]'
    }`;
  // Layout reacts to the width of the printer card (container query), not the
  // viewport: narrow cards stack the motion pads above the settings column,
  // wide cards place them side by side.
  const panelContainer = '@container';
  const panelLayout =
    'flex flex-col gap-4 p-3 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] @xl:flex-row @xl:items-start @xl:gap-6';
  const motionGroup = 'flex flex-col gap-2 items-center shrink-0 @xl:items-start';
  const stepRow = 'flex flex-wrap justify-center gap-1 max-w-[244px] @xl:justify-start';
  const axisHomeBtn = `${homeBtn} w-12`;

  // Fixed jog layout, identical for every provider:
  //   [ ] [Y+] [ ]   [⌂ ALL]   [Z+]
  //   [X-] [⌂] [X+]  [⌂ X]     [⌂ Z]
  //   [ ] [Y-] [ ]   [⌂ Y]     [Z-]
  // followed by the step sizes underneath.
  const renderMotionControls = (isBusy: boolean) => (
    <div data-testid="motion-controls" className={motionGroup}>
      <div className="flex gap-3">
        {/* ── XY cross with Home XY in the centre ── */}
        <div data-testid="xy-cross" className="grid grid-cols-[repeat(3,2.5rem)] grid-rows-[repeat(3,2.5rem)] gap-1">
          <button className={`${joyBtn} col-start-2 row-start-1`} disabled={isBusy} onClick={() => moveMut.mutate({ axis: 'y', distance: xyStep })} title="Y+">
            <ArrowUp size={16} />
          </button>
          <button className={`${joyBtn} col-start-1 row-start-2`} disabled={isBusy} onClick={() => moveMut.mutate({ axis: 'x', distance: -xyStep })} title="X−">
            <ArrowLeft size={16} />
          </button>
          <button className={`${homeBtn} col-start-2 row-start-2`} disabled={isBusy} onClick={() => homeMut.mutate(['x', 'y'])} title="Home XY">
            <Home size={14} />
          </button>
          <button className={`${joyBtn} col-start-3 row-start-2`} disabled={isBusy} onClick={() => moveMut.mutate({ axis: 'x', distance: xyStep })} title="X+">
            <ArrowRight size={16} />
          </button>
          <button className={`${joyBtn} col-start-2 row-start-3`} disabled={isBusy} onClick={() => moveMut.mutate({ axis: 'y', distance: -xyStep })} title="Y−">
            <ArrowDown size={16} />
          </button>
        </div>

        {/* ── Homing: all / X / Y ── */}
        <div data-testid="home-column" className="flex flex-col gap-1">
          <button className={axisHomeBtn} disabled={isBusy} onClick={() => homeMut.mutate(undefined)} title="Home All">
            <Home size={13} />
            <span>ALL</span>
          </button>
          <button className={axisHomeBtn} disabled={isBusy} onClick={() => homeMut.mutate(['x'])} title="Home X">
            <Home size={13} />
            <span>X</span>
          </button>
          <button className={axisHomeBtn} disabled={isBusy} onClick={() => homeMut.mutate(['y'])} title="Home Y">
            <Home size={13} />
            <span>Y</span>
          </button>
        </div>

        {/* ── Z: up / home / down ── */}
        <div data-testid="z-column" className="flex flex-col gap-1">
          <button className={joyBtn} disabled={isBusy} onClick={() => moveMut.mutate({ axis: 'z', distance: xyStep })} title="Z+">
            <ArrowUp size={16} />
          </button>
          <button className={`${homeBtn} w-10`} disabled={isBusy} onClick={() => homeMut.mutate(['z'])} title="Home Z">
            <Home size={13} />
            <span>Z</span>
          </button>
          <button className={joyBtn} disabled={isBusy} onClick={() => moveMut.mutate({ axis: 'z', distance: -xyStep })} title="Z−">
            <ArrowDown size={16} />
          </button>
        </div>
      </div>

      {/* Step sizes (XY and Z) */}
      <div className={stepRow}>
        {XY_STEPS.map((s) => (
          <button key={s} className={stepBtnClass(xyStep === s)} onClick={() => setXyStep(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
  const rightPanel = 'flex flex-col gap-3 flex-1 min-w-0 w-full';
  const inputClass =
    'w-16 shrink-0 rounded px-2 py-1 text-sm bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent)]';

  if (usesGenericControls) {
    const prusaBusy = moveMut.isPending || homeMut.isPending || disableSteppersMut.isPending;

    return (
      <div className={panelContainer}>
      <div className={panelLayout}>
        {renderMotionControls(prusaBusy)}

        {/* ── Right panel ── */}
        <div className={rightPanel}>
          <div className="grid grid-cols-3 gap-2 p-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)]">
            {(['x', 'y', 'z'] as const).map((axis) => (
              <div key={axis} className="flex flex-col min-w-0">
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider truncate">
                  {axis.toUpperCase()}
                </span>
                <span className="text-sm font-mono font-semibold tabular-nums truncate">
                  {formatAxis(pos[axis])}
                </span>
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">
                {t('printers.klipper.extrusionLength', 'Extrusion length')}
              </label>
              <input type="number" className={inputClass} value={extrudeLength} min={0.1} step={1} onChange={(e) => setExtrudeLength(Number(e.target.value))} />
              <span className="text-xs text-[var(--text-muted)] w-8 shrink-0">mm</span>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">
                {t('printers.klipper.extrusionSpeed', 'Extrusion speed')}
              </label>
              <input type="number" className={inputClass} value={extrudeSpeed} min={1} step={1} onChange={(e) => setExtrudeSpeed(Number(e.target.value))} />
              <span className="text-xs text-[var(--text-muted)] w-8 shrink-0">mm/s</span>
            </div>
            <div className="flex gap-2">
              <button className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium min-w-0 ${secondaryControlBtn}`} disabled={extrudeMut.isPending} onClick={() => extrudeMut.mutate(-extrudeLength)}>
                {t('printers.klipper.retract', 'Retract')}
                <ChevronUp size={14} />
              </button>
              <button className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium min-w-0 ${secondaryControlBtn}`} disabled={extrudeMut.isPending} onClick={() => extrudeMut.mutate(extrudeLength)}>
                {t('printers.klipper.extrude', 'Extrude')}
                <ChevronDown size={14} />
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <Thermometer size={14} className="text-orange-400 shrink-0" />
              <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">{t('printers.klipper.nozzle', 'Nozzle')}</label>
              <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12 shrink-0 text-right">{Math.round(temps.nozzle ?? 0)}°C</span>
              <input type="number" aria-label="Nozzle temperature target" className={inputClass} value={nozzleInput} min={0} max={350} placeholder={String(Math.round(temps.nozzle_target ?? 0) || '—')} onChange={(e) => setNozzleInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && nozzleInput !== '') nozzleMut.mutate(Number(nozzleInput)); }} />
              <button aria-label="Nozzle" className={`px-2 py-1 rounded text-xs shrink-0 ${secondaryControlBtn}`} disabled={nozzleMut.isPending || nozzleInput === ''} onClick={() => nozzleMut.mutate(Number(nozzleInput))}>Set</button>
            </div>
            <div className="flex items-center gap-2">
              <Thermometer size={14} className="text-blue-400 shrink-0" />
              <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">{t('printers.klipper.bed', 'Bed')}</label>
              <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12 shrink-0 text-right">{Math.round(temps.bed ?? 0)}°C</span>
              <input type="number" aria-label="Bed temperature target" className={inputClass} value={bedInput} min={0} max={140} placeholder={String(Math.round(temps.bed_target ?? 0) || '—')} onChange={(e) => setBedInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && bedInput !== '') bedMut.mutate(Number(bedInput)); }} />
              <button aria-label="Bed" className={`px-2 py-1 rounded text-xs shrink-0 ${secondaryControlBtn}`} disabled={bedMut.isPending || bedInput === ''} onClick={() => bedMut.mutate(Number(bedInput))}>Set</button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">Stepper motors</span>
            <button
              className={`flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium min-w-0 ${secondaryControlBtn}`}
              disabled={disableSteppersMut.isPending}
              onClick={() => disableSteppersMut.mutate()}
            >
              Disable steppers
            </button>
          </div>
        </div>
      </div>
      </div>
    );
  }

  return (
    <div className={panelContainer}>
    <div className={panelLayout}>
      {renderMotionControls(busy)}

      {/* ── Right panel ── */}
      <div className={rightPanel}>
        {/* Position readout */}
        <div className="grid grid-cols-3 gap-2 p-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)]">
          {(['x', 'y', 'z'] as const).map((axis) => (
            <div key={axis} className="flex flex-col min-w-0">
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider truncate">
                {axis.toUpperCase()}
              </span>
              <span className="text-sm font-mono font-semibold tabular-nums truncate">
                {formatAxis(pos[axis])}
              </span>
            </div>
          ))}
        </div>

        {/* Extrusion controls */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">
              {t('printers.klipper.extrusionLength', 'Extrusion length')}
            </label>
            <input
              type="number"
              className={inputClass}
              value={extrudeLength}
              min={0.1}
              step={1}
              onChange={(e) => setExtrudeLength(Number(e.target.value))}
            />
            <span className="text-xs text-[var(--text-muted)] w-8 shrink-0">mm</span>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">
              {t('printers.klipper.extrusionSpeed', 'Extrusion speed')}
            </label>
            <input
              type="number"
              className={inputClass}
              value={extrudeSpeed}
              min={1}
              step={1}
              onChange={(e) => setExtrudeSpeed(Number(e.target.value))}
            />
            <span className="text-xs text-[var(--text-muted)] w-8 shrink-0">mm/s</span>
          </div>
          <div className="flex gap-2">
            <button
              className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium min-w-0 ${secondaryControlBtn}`}
              disabled={extrudeMut.isPending}
              onClick={() => extrudeMut.mutate(-extrudeLength)}
            >
              {t('printers.klipper.retract', 'Retract')}
              <ChevronUp size={14} />
            </button>
            <button
              className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium min-w-0 ${secondaryControlBtn}`}
              disabled={extrudeMut.isPending}
              onClick={() => extrudeMut.mutate(extrudeLength)}
            >
              {t('printers.klipper.extrude', 'Extrude')}
              <ChevronDown size={14} />
            </button>
          </div>
        </div>

        {/* Temperature controls */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <Thermometer size={14} className="text-orange-400 shrink-0" />
            <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">
              {t('printers.klipper.nozzle', 'Nozzle')}
            </label>
            <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12 shrink-0 text-right">
              {Math.round(temps.nozzle ?? 0)}°C
            </span>
            <input
              type="number"
              aria-label="Nozzle temperature target"
              className={inputClass}
              value={nozzleInput}
              min={0}
              max={350}
              placeholder={String(Math.round(temps.nozzle_target ?? 0) || '—')}
              onChange={(e) => setNozzleInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && nozzleInput !== '') nozzleMut.mutate(Number(nozzleInput));
              }}
            />
            <button
              aria-label="Nozzle"
              className={`px-2 py-1 rounded text-xs shrink-0 ${secondaryControlBtn}`}
              disabled={nozzleMut.isPending || nozzleInput === ''}
              onClick={() => nozzleMut.mutate(Number(nozzleInput))}
            >
              Set
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Thermometer size={14} className="text-blue-400 shrink-0" />
            <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">
              {t('printers.klipper.bed', 'Bed')}
            </label>
            <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12 shrink-0 text-right">
              {Math.round(temps.bed ?? 0)}°C
            </span>
            <input
              type="number"
              aria-label="Bed temperature target"
              className={inputClass}
              value={bedInput}
              min={0}
              max={140}
              placeholder={String(Math.round(temps.bed_target ?? 0) || '—')}
              onChange={(e) => setBedInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && bedInput !== '') bedMut.mutate(Number(bedInput));
              }}
            />
            <button
              aria-label="Bed"
              className={`px-2 py-1 rounded text-xs shrink-0 ${secondaryControlBtn}`}
              disabled={bedMut.isPending || bedInput === ''}
              onClick={() => bedMut.mutate(Number(bedInput))}
            >
              Set
            </button>
          </div>
          {hasChamberHeater && (
            <div className="flex items-center gap-2">
              <Thermometer size={14} className="text-green-400 shrink-0" />
              <label className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">
                {t('printers.klipper.chamber', 'Chamber')}
              </label>
              <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12 shrink-0 text-right">
                {Math.round(temps.chamber ?? 0)}°C
              </span>
              <input
                type="number"
                aria-label="Chamber temperature target"
                className={inputClass}
                value={chamberInput}
                min={0}
                max={chamberMax}
                placeholder={String(Math.round(temps.chamber_target ?? 0) || '—')}
                title={`0-${chamberMax}°C (0 = off)`}
                onChange={(e) => setChamberInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submitChamber();
                }}
              />
              <button
                aria-label="Chamber"
                className={`px-2 py-1 rounded text-xs shrink-0 ${secondaryControlBtn}`}
                disabled={chamberMut.isPending || chamberInput === ''}
                onClick={submitChamber}
              >
                Set
              </button>
            </div>
          )}
        </div>

        {/* Z-offset fine adjustment */}
        <div className="flex flex-col gap-1.5">
          <div className="flex gap-1 flex-wrap">
            {Z_OFFSET_STEPS.map((s) => (
              <button key={s} className={stepBtnClass(zOffsetStep === s)} onClick={() => setZOffsetStep(s)}>
                {s}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-[var(--text-muted)] flex-1 min-w-0">
              {t('printers.klipper.zOffset', 'Z-Offset')}{' '}
              <span className="font-mono tabular-nums whitespace-nowrap">
                {typeof zOffset === 'number' ? `${zOffset.toFixed(3)} mm` : '—'}
              </span>
            </span>
            <div className="flex gap-1 ml-auto">
              <button
                className={homeBtn}
                disabled={zOffsetMut.isPending}
                onClick={() => zOffsetMut.mutate({ amount: zOffsetStep })}
                title={`Z-Offset +${zOffsetStep}`}
              >
                <ChevronUp size={14} />
              </button>
              <button
                className={homeBtn}
                disabled={zOffsetMut.isPending}
                onClick={() => zOffsetMut.mutate({ amount: -zOffsetStep })}
                title={`Z-Offset −${zOffsetStep}`}
              >
                <ChevronDown size={14} />
              </button>
              <button
                className="flex items-center justify-center w-10 h-10 rounded bg-[var(--accent)] hover:bg-[var(--accent-light)] text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                disabled={zOffsetMut.isPending}
                onClick={() => zOffsetMut.mutate({ amount: 0, save: true })}
                title={t('printers.klipper.saveZOffset', 'Save Z-Offset to config')}
              >
                <Save size={14} />
              </button>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-[var(--text-muted)] flex-1 min-w-0 truncate">Stepper motors</span>
          <button
            className={`flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium min-w-0 ${secondaryControlBtn}`}
            disabled={disableSteppersMut.isPending}
            onClick={() => disableSteppersMut.mutate()}
          >
            Disable steppers
          </button>
        </div>
      </div>
    </div>
    </div>
  );
}
