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
  position?: { x?: number; y?: number; z?: number };
  z_offset?: number;
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

  const onError = () =>
    showToast(t('printers.toast.failedToSendCommand', 'Command failed'), 'error');

  const moveMut = useMutation({
    mutationFn: ({ axis, distance }: { axis: 'x' | 'y' | 'z'; distance: number }) =>
      api.axisJog(printer.id, axis, distance),
    onError,
  });

  const homeMut = useMutation({
    mutationFn: (axes?: string[]) => {
      if (printer.provider === 'prusalink') {
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
      return printer.provider === 'prusalink'
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

  const disableSteppersMut = useMutation({
    mutationFn: () => api.disableSteppers(printer.id),
    onError,
  });

  const pos = status?.position ?? {};
  const zOffset = status?.z_offset ?? 0;
  const temps = status?.temperatures ?? {};
  const busy = moveMut.isPending || homeMut.isPending;

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
  const inputClass =
    'w-16 rounded px-2 py-1 text-sm bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent)]';

  if (printer.provider === 'prusalink') {
    const prusaBusy = moveMut.isPending || homeMut.isPending || disableSteppersMut.isPending;

    return (
      <div className="flex flex-wrap gap-6 p-3 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)]">
        {/* ── XY jog grid ── */}
        <div className="flex flex-col gap-1">
          <div className="flex gap-1">
            <button className={joyBtn} disabled={prusaBusy} onClick={() => moveMut.mutate({ axis: 'y', distance: xyStep })} title="Y+">
              <ArrowUp size={16} />
            </button>
            <div className="w-10" />
            <button className={homeBtn} disabled={prusaBusy} onClick={() => homeMut.mutate(undefined)} title="Home All">
              <Home size={13} />
              <span>ALL</span>
            </button>
          </div>

          <div className="flex gap-1">
            <button className={joyBtn} disabled={prusaBusy} onClick={() => moveMut.mutate({ axis: 'x', distance: -xyStep })} title="X−">
              <ArrowLeft size={16} />
            </button>
            <button className={homeBtn} disabled={prusaBusy} onClick={() => homeMut.mutate(['x', 'y'])} title="Home XY">
              <Home size={13} />
            </button>
            <button className={joyBtn} disabled={prusaBusy} onClick={() => moveMut.mutate({ axis: 'x', distance: xyStep })} title="X+">
              <ArrowRight size={16} />
            </button>
            <button className={homeBtn} disabled={prusaBusy} onClick={() => homeMut.mutate(['x'])} title="Home X">
              <Home size={13} />
              <span>X</span>
            </button>
          </div>

          <div className="flex gap-1">
            <button className={joyBtn} disabled={prusaBusy} onClick={() => moveMut.mutate({ axis: 'y', distance: -xyStep })} title="Y−">
              <ArrowDown size={16} />
            </button>
            <div className="w-10" />
            <div className="w-10" />
            <button className={homeBtn} disabled={prusaBusy} onClick={() => homeMut.mutate(['y'])} title="Home Y">
              <Home size={13} />
              <span>Y</span>
            </button>
          </div>

          <div className="flex gap-1 mt-1 flex-wrap">
            {XY_STEPS.map((s) => (
              <button key={s} className={stepBtnClass(xyStep === s)} onClick={() => setXyStep(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* ── Z jog ── */}
        <div className="flex flex-col items-center gap-1">
          <button className={joyBtn} disabled={prusaBusy} onClick={() => moveMut.mutate({ axis: 'z', distance: xyStep })} title="Z+">
            <ArrowUp size={16} />
          </button>
          <button className={homeBtn} disabled={prusaBusy} onClick={() => homeMut.mutate(['z'])} title="Home Z">
            <Home size={13} />
            <span>Z</span>
          </button>
          <button className={joyBtn} disabled={prusaBusy} onClick={() => moveMut.mutate({ axis: 'z', distance: -xyStep })} title="Z−">
            <ArrowDown size={16} />
          </button>
        </div>

        {/* ── Right panel ── */}
        <div className="flex flex-col gap-3 min-w-[230px] flex-1">
          <div className="grid grid-cols-3 gap-3 p-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)]">
            {(['x', 'y', 'z'] as const).map((axis) => (
              <div key={axis} className="flex flex-col">
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
                  {axis.toUpperCase()} [{((pos as Record<string, number>)[axis] ?? 0).toFixed(2)}]
                </span>
                <span className="text-sm font-mono font-semibold tabular-nums">
                  {((pos as Record<string, number>)[axis] ?? 0).toFixed(2)}
                </span>
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <label className="text-xs text-[var(--text-muted)] w-32 shrink-0">
                {t('printers.klipper.extrusionLength', 'Extrusion length')}
              </label>
              <input type="number" className={inputClass} value={extrudeLength} min={0.1} step={1} onChange={(e) => setExtrudeLength(Number(e.target.value))} />
              <span className="text-xs text-[var(--text-muted)]">mm</span>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-[var(--text-muted)] w-32 shrink-0">
                {t('printers.klipper.extrusionSpeed', 'Extrusion speed')}
              </label>
              <input type="number" className={inputClass} value={extrudeSpeed} min={1} step={1} onChange={(e) => setExtrudeSpeed(Number(e.target.value))} />
              <span className="text-xs text-[var(--text-muted)]">mm/s</span>
            </div>
            <div className="flex gap-2">
              <button className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium ${secondaryControlBtn}`} disabled={extrudeMut.isPending} onClick={() => extrudeMut.mutate(-extrudeLength)}>
                {t('printers.klipper.retract', 'Retract')}
                <ChevronUp size={14} />
              </button>
              <button className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium ${secondaryControlBtn}`} disabled={extrudeMut.isPending} onClick={() => extrudeMut.mutate(extrudeLength)}>
                {t('printers.klipper.extrude', 'Extrude')}
                <ChevronDown size={14} />
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <Thermometer size={14} className="text-orange-400 shrink-0" />
              <label className="text-xs text-[var(--text-muted)] w-16 shrink-0">{t('printers.klipper.nozzle', 'Nozzle')}</label>
              <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12">{Math.round(temps.nozzle ?? 0)}°C</span>
              <input type="number" aria-label="Nozzle temperature target" className={inputClass} value={nozzleInput} min={0} max={350} placeholder={String(Math.round(temps.nozzle_target ?? 0) || '—')} onChange={(e) => setNozzleInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && nozzleInput !== '') nozzleMut.mutate(Number(nozzleInput)); }} />
              <button aria-label="Nozzle" className={`px-2 py-1 rounded text-xs ${secondaryControlBtn}`} disabled={nozzleMut.isPending || nozzleInput === ''} onClick={() => nozzleMut.mutate(Number(nozzleInput))}>Set</button>
            </div>
            <div className="flex items-center gap-2">
              <Thermometer size={14} className="text-blue-400 shrink-0" />
              <label className="text-xs text-[var(--text-muted)] w-16 shrink-0">{t('printers.klipper.bed', 'Bed')}</label>
              <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12">{Math.round(temps.bed ?? 0)}°C</span>
              <input type="number" aria-label="Bed temperature target" className={inputClass} value={bedInput} min={0} max={140} placeholder={String(Math.round(temps.bed_target ?? 0) || '—')} onChange={(e) => setBedInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && bedInput !== '') bedMut.mutate(Number(bedInput)); }} />
              <button aria-label="Bed" className={`px-2 py-1 rounded text-xs ${secondaryControlBtn}`} disabled={bedMut.isPending || bedInput === ''} onClick={() => bedMut.mutate(Number(bedInput))}>Set</button>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)] flex-1">Stepper motors</span>
            <button
              className={`flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium ${secondaryControlBtn}`}
              disabled={disableSteppersMut.isPending}
              onClick={() => disableSteppersMut.mutate()}
            >
              Disable steppers
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-6 p-3 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)]">
      {/* ── XY jog grid ── */}
      <div className="flex flex-col gap-1">
        {/* row 1: Y+ | spacer | Home All */}
        <div className="flex gap-1">
          <button
            className={joyBtn}
            disabled={busy}
            onClick={() => moveMut.mutate({ axis: 'y', distance: xyStep })}
            title="Y+"
          >
            <ArrowUp size={16} />
          </button>
          <div className="w-10" />
          <button
            className={homeBtn}
            disabled={busy}
            onClick={() => homeMut.mutate(undefined)}
            title="Home All"
          >
            <Home size={13} />
            <span>ALL</span>
          </button>
        </div>

        {/* row 2: X- | Home XY | X+ | Home X */}
        <div className="flex gap-1">
          <button
            className={joyBtn}
            disabled={busy}
            onClick={() => moveMut.mutate({ axis: 'x', distance: -xyStep })}
            title="X−"
          >
            <ArrowLeft size={16} />
          </button>
          <button
            className={homeBtn}
            disabled={busy}
            onClick={() => homeMut.mutate(['x', 'y'])}
            title="Home XY"
          >
            <Home size={13} />
          </button>
          <button
            className={joyBtn}
            disabled={busy}
            onClick={() => moveMut.mutate({ axis: 'x', distance: xyStep })}
            title="X+"
          >
            <ArrowRight size={16} />
          </button>
          <button
            className={homeBtn}
            disabled={busy}
            onClick={() => homeMut.mutate(['x'])}
            title="Home X"
          >
            <Home size={13} />
            <span>X</span>
          </button>
        </div>

        {/* row 3: Y- | spacer | Home Y */}
        <div className="flex gap-1">
          <button
            className={joyBtn}
            disabled={busy}
            onClick={() => moveMut.mutate({ axis: 'y', distance: -xyStep })}
            title="Y−"
          >
            <ArrowDown size={16} />
          </button>
          <div className="w-10" />
          <div className="w-10" />
          <button
            className={homeBtn}
            disabled={busy}
            onClick={() => homeMut.mutate(['y'])}
            title="Home Y"
          >
            <Home size={13} />
            <span>Y</span>
          </button>
        </div>

        {/* XY step sizes */}
        <div className="flex gap-1 mt-1 flex-wrap">
          {XY_STEPS.map((s) => (
            <button key={s} className={stepBtnClass(xyStep === s)} onClick={() => setXyStep(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* ── Z jog ── */}
      <div className="flex flex-col items-center gap-1">
        <button
          className={joyBtn}
          disabled={busy}
          onClick={() => moveMut.mutate({ axis: 'z', distance: xyStep })}
          title="Z+"
        >
          <ArrowUp size={16} />
        </button>
        <button
          className={homeBtn}
          disabled={busy}
          onClick={() => homeMut.mutate(['z'])}
          title="Home Z"
        >
          <Home size={13} />
          <span>Z</span>
        </button>
        <button
          className={joyBtn}
          disabled={busy}
          onClick={() => moveMut.mutate({ axis: 'z', distance: -xyStep })}
          title="Z−"
        >
          <ArrowDown size={16} />
        </button>
      </div>

      {/* ── Right panel ── */}
      <div className="flex flex-col gap-3 min-w-[230px] flex-1">
        {/* Position readout */}
        <div className="grid grid-cols-3 gap-3 p-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)]">
          {(['x', 'y', 'z'] as const).map((axis) => (
            <div key={axis} className="flex flex-col">
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
                {axis.toUpperCase()} [{((pos as Record<string, number>)[axis] ?? 0).toFixed(2)}]
              </span>
              <span className="text-sm font-mono font-semibold tabular-nums">
                {((pos as Record<string, number>)[axis] ?? 0).toFixed(2)}
              </span>
            </div>
          ))}
        </div>

        {/* Extrusion controls */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--text-muted)] w-32 shrink-0">
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
            <span className="text-xs text-[var(--text-muted)]">mm</span>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--text-muted)] w-32 shrink-0">
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
            <span className="text-xs text-[var(--text-muted)]">mm/s</span>
          </div>
          <div className="flex gap-2">
            <button
              className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium ${secondaryControlBtn}`}
              disabled={extrudeMut.isPending}
              onClick={() => extrudeMut.mutate(-extrudeLength)}
            >
              {t('printers.klipper.retract', 'Retract')}
              <ChevronUp size={14} />
            </button>
            <button
              className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-sm font-medium ${secondaryControlBtn}`}
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
            <label className="text-xs text-[var(--text-muted)] w-16 shrink-0">
              {t('printers.klipper.nozzle', 'Nozzle')}
            </label>
            <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12">
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
              className={`px-2 py-1 rounded text-xs ${secondaryControlBtn}`}
              disabled={nozzleMut.isPending || nozzleInput === ''}
              onClick={() => nozzleMut.mutate(Number(nozzleInput))}
            >
              Set
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Thermometer size={14} className="text-blue-400 shrink-0" />
            <label className="text-xs text-[var(--text-muted)] w-16 shrink-0">
              {t('printers.klipper.bed', 'Bed')}
            </label>
            <span className="text-xs font-mono tabular-nums text-[var(--text-secondary)] w-12">
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
              className={`px-2 py-1 rounded text-xs ${secondaryControlBtn}`}
              disabled={bedMut.isPending || bedInput === ''}
              onClick={() => bedMut.mutate(Number(bedInput))}
            >
              Set
            </button>
          </div>
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
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)] flex-1">
              {t('printers.klipper.zOffset', 'Z-Offset')}{' '}
              <span className="font-mono tabular-nums">{zOffset.toFixed(3)} mm</span>
            </span>
            <div className="flex gap-1">
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
      </div>
    </div>
  );
}
