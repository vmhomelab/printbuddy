import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Home, Loader2, Pencil, Thermometer, Video } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { Printer, PrusaConnectLocalControls, PrusaConnectLocalVerbArgument } from '../api/client';

type ToastType = 'success' | 'error' | 'warning' | 'info' | 'loading';
type CommandArgs = Record<string, string | number | boolean>;

const STEPS = [0.1, 1, 10];
const NOZZLE_DIAMETERS = [0.25, 0.3, 0.4, 0.5, 0.6, 0.8];
const XY_FEEDRATE = 3000;
const Z_FEEDRATE = 600;
// Sliders stop at 300 % like Prusa Connect Local; the number field still accepts the full range.
const PERCENT_SLIDER_MAX = 300;

interface Props {
  printer: Printer;
  canControl: boolean;
  canUpdate: boolean;
  showToast: (msg: string, type?: ToastType) => void;
}

function argument(controls: PrusaConnectLocalControls | undefined, verb: string, name: string): PrusaConnectLocalVerbArgument | undefined {
  return controls?.verbs[verb]?.find((arg) => arg.name === name);
}

function formatTemp(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value)}°C`;
}

// The panel sits inside a printer card, so columns follow the panel width, not the viewport.
const columnsClass = 'grid gap-3 grid-cols-[repeat(auto-fit,minmax(min(100%,17rem),1fr))] items-start';
const sectionClass = 'flex flex-col gap-3 p-3 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)] min-w-0';
const headingClass = 'text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider';
const labelClass = 'text-xs text-[var(--text-muted)]';
const actionBtn =
  'px-3 py-1.5 rounded text-sm font-medium border border-[var(--accent)] bg-[var(--bg-primary)] hover:bg-[var(--accent)] hover:text-white text-[var(--accent)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer';
const dangerBtn =
  'px-3 py-1.5 rounded text-sm font-medium border border-red-500 text-red-400 hover:bg-red-500 hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer';
const joyBtn =
  'flex items-center justify-center w-10 h-10 rounded bg-[var(--accent)] hover:bg-[var(--accent-light)] active:bg-[var(--accent-dark)] text-white shadow-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer select-none';
const homePadBtn =
  'flex items-center justify-center w-10 h-10 rounded border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)] hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer select-none';
const numberInputClass =
  'w-[4.5rem] shrink-0 rounded px-2 py-1 text-sm tabular-nums bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent)]';

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={sectionClass}>
      <h4 className={headingClass}>{title}</h4>
      {children}
    </section>
  );
}

function Segmented<T extends string | number | boolean>({
  options,
  value,
  disabled,
  onSelect,
  label,
}: {
  options: { value: T; label: string }[];
  value: T | null;
  disabled: boolean;
  onSelect: (value: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded border border-[var(--border-color)] overflow-hidden w-fit">
      {options.map((option, index) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            aria-pressed={active}
            className={`px-2.5 py-1 text-xs transition-colors cursor-pointer select-none disabled:opacity-40 disabled:cursor-not-allowed ${
              index > 0 ? 'border-l border-[var(--border-color)]' : ''
            } ${active ? 'bg-[var(--accent)] text-white' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]'}`}
            disabled={disabled}
            onClick={() => onSelect(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function PercentControl({
  label,
  value,
  spec,
  disabled,
  onCommit,
}: {
  label: string;
  value: number | null;
  spec?: PrusaConnectLocalVerbArgument;
  disabled: boolean;
  onCommit: (value: number) => void;
}) {
  const min = spec?.minimum ?? 0;
  const max = spec?.maximum ?? 100;
  const [draft, setDraft] = useState<number | null>(null);
  const shown = draft ?? value ?? min;

  useEffect(() => setDraft(null), [value]);

  const commit = (next: number) => {
    const clamped = Math.min(max, Math.max(min, Math.round(next)));
    setDraft(null);
    if (clamped !== value) onCommit(clamped);
  };

  return (
    <div className="flex flex-col gap-1 min-w-0">
      <span className={labelClass}>{label}</span>
      <div className="flex items-center gap-2 min-w-0">
        <input
          type="range"
          aria-label={label}
          className="flex-1 min-w-0 accent-[var(--accent)]"
          min={min}
          max={Math.min(max, PERCENT_SLIDER_MAX)}
          value={Math.min(shown, PERCENT_SLIDER_MAX)}
          disabled={disabled}
          onChange={(e) => setDraft(Number(e.target.value))}
          onPointerUp={() => draft !== null && commit(draft)}
          onKeyUp={(e) => e.key.startsWith('Arrow') && draft !== null && commit(draft)}
        />
        <input
          type="number"
          aria-label={`${label} %`}
          className={numberInputClass}
          min={min}
          max={max}
          value={draft ?? value ?? ''}
          placeholder="—"
          disabled={disabled}
          onChange={(e) => setDraft(Number(e.target.value))}
          onBlur={() => draft !== null && commit(draft)}
          onKeyDown={(e) => e.key === 'Enter' && draft !== null && commit(draft)}
        />
        <span className="text-xs text-[var(--text-muted)] w-3 shrink-0">%</span>
      </div>
    </div>
  );
}

function TemperatureRow({
  label,
  current,
  target,
  spec,
  disabled,
  onSet,
}: {
  label: string;
  current: number | null;
  target: number | null;
  spec?: PrusaConnectLocalVerbArgument;
  disabled: boolean;
  onSet: (target: number) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState('');

  const submit = () => {
    if (input === '') return;
    onSet(Number(input));
    setEditing(false);
    setInput('');
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 min-w-0">
        <Thermometer size={16} className="text-orange-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm truncate">{label}</p>
          <p className="text-xs text-[var(--text-muted)]">
            {target
              ? t('printers.prusaConnectLocal.controls.target', { value: formatTemp(target) })
              : t('printers.prusaConnectLocal.controls.off')}
          </p>
        </div>
        <span className="text-base font-mono tabular-nums shrink-0">{formatTemp(current)}</span>
        <button
          className="p-1.5 rounded text-[var(--text-muted)] hover:text-[var(--accent)] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shrink-0"
          aria-label={t('printers.prusaConnectLocal.controls.editTarget', { name: label })}
          aria-expanded={editing}
          disabled={disabled}
          onClick={() => setEditing((open) => !open)}
        >
          <Pencil size={14} />
        </button>
      </div>
      {editing && (
        <div className="flex items-center gap-2 pl-6">
          <input
            type="number"
            autoFocus
            aria-label={t('printers.prusaConnectLocal.controls.editTarget', { name: label })}
            className={numberInputClass}
            min={spec?.minimum ?? 0}
            max={spec?.maximum}
            value={input}
            placeholder={String(Math.round(target ?? 0))}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
              if (e.key === 'Escape') setEditing(false);
            }}
          />
          <span className="text-xs text-[var(--text-muted)]">°C</span>
          <button className={actionBtn} disabled={disabled || input === ''} onClick={submit}>
            {t('printers.prusaConnectLocal.controls.set')}
          </button>
          <button className={actionBtn} disabled={disabled} onClick={() => onSet(0)}>
            {t('printers.prusaConnectLocal.controls.off')}
          </button>
        </div>
      )}
    </div>
  );
}

export function PrusaConnectLocalControlPanel({ printer, canControl, canUpdate, showToast }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [step, setStep] = useState(1);
  const [chamberFan, setChamberFan] = useState<number | null>(null);
  const [chamberLight, setChamberLight] = useState<number | null>(null);
  const [hostnameInput, setHostnameInput] = useState<string | null>(null);

  const queryKey = ['prusaConnectLocalControls', printer.id];
  const { data: controls, isLoading, error } = useQuery({
    queryKey,
    queryFn: () => api.getPrusaConnectLocalControls(printer.id),
    refetchInterval: 3000,
  });

  const command = useMutation({
    mutationFn: ({ verb, args }: { verb: string; args?: CommandArgs }) =>
      api.sendPrusaConnectLocalCommand(printer.id, verb, args),
    onSuccess: () => {
      // The device record catches up with the printer's next telemetry frame.
      setTimeout(() => queryClient.invalidateQueries({ queryKey }), 800);
    },
    onError: (e: unknown) =>
      showToast(
        e instanceof Error ? e.message : t('printers.toast.failedToSendCommand', 'Command failed'),
        'error',
      ),
  });

  const detectCamera = useMutation({
    mutationFn: () => api.detectPrusaConnectLocalCamera(printer.id),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey });
      // The printer row now carries (or no longer carries) a derived camera.
      queryClient.invalidateQueries({ queryKey: ['printers'] });
      if (result.camera) {
        showToast(t('printers.prusaConnectLocal.controls.cameraFound', { name: result.camera.name }), 'success');
      } else if (result.webrtc_only.length > 0) {
        showToast(t('printers.prusaConnectLocal.controls.cameraWebrtcOnly', { name: result.webrtc_only.join(', ') }), 'warning');
      } else {
        showToast(t('printers.prusaConnectLocal.controls.cameraNone'), 'info');
      }
    },
    onError: (e: unknown) => showToast(e instanceof Error ? e.message : String(e), 'error'),
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-3 text-sm text-[var(--text-muted)]">
        <Loader2 className="w-4 h-4 animate-spin" />
        {t('printers.prusaConnectLocal.controls.loading')}
      </div>
    );
  }
  if (error || !controls) {
    return (
      <div className="p-3 text-sm text-red-400">
        {error instanceof Error ? error.message : t('printers.prusaConnectLocal.controls.unavailable')}
      </div>
    );
  }

  const has = (verb: string) => verb in controls.verbs;
  const send = (verb: string, args?: CommandArgs) => command.mutate({ verb, args });
  const blocked = !canControl || !controls.can_operate || !controls.connected;
  const confirmAndSend = (message: string, verb: string) => {
    if (window.confirm(message)) send(verb);
  };

  const move = (axis: 'x' | 'y' | 'z', direction: 1 | -1) => {
    const distance = direction * step;
    if (axis === 'z') send('move_z', { distance, feedrate: Z_FEEDRATE });
    else send('move', { [axis]: distance, feedrate: XY_FEEDRATE });
  };

  const activeTool = controls.tools.find((tool) => tool.active) ?? controls.tools[0];
  const isReady = controls.state === 'READY';
  const fanSpec = argument(controls, 'set_chamber_fan_target', 'chamber.fan_pwm_target');
  const hasChamber = has('set_chamber_fan_target') || has('set_chamber_led_intensity');
  const hasNozzleSettings = has('set_tool_nozzle_diameter') || has('set_tool_high_flow') || has('set_tool_hardened');
  const onOff = [
    { value: false, label: t('printers.prusaConnectLocal.controls.off') },
    { value: true, label: t('printers.prusaConnectLocal.controls.on') },
  ];

  return (
    <div className="flex flex-col gap-3">
      {blocked && (
        <p className="text-xs text-yellow-500">
          {!controls.connected
            ? t('printers.prusaConnectLocal.controls.offline')
            : !controls.can_operate
              ? t('printers.prusaConnectLocal.controls.noOperateGrant')
              : t('printers.permission.noControl')}
        </p>
      )}
      <div className={columnsClass}>
        {(has('move') || has('move_z') || has('home')) && (
          <Section title={t('printers.prusaConnectLocal.controls.coordinates')}>
            <div className="grid grid-cols-3 gap-2">
              {(['x', 'y', 'z'] as const).map((axis) => (
                <div key={axis} className="rounded border border-[var(--border-color)] px-2 py-1">
                  <p className="text-[10px] text-[var(--text-muted)] uppercase">{axis}</p>
                  <p className="text-sm font-mono tabular-nums truncate">
                    {controls.position[axis] === null ? '—' : controls.position[axis]!.toFixed(2)}
                  </p>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className={labelClass}>{t('printers.prusaConnectLocal.controls.step')}</span>
              <Segmented
                label={t('printers.prusaConnectLocal.controls.step')}
                options={STEPS.map((value) => ({ value, label: `${value}` }))}
                value={step}
                disabled={false}
                onSelect={setStep}
              />
              <span className={labelClass}>mm</span>
            </div>
            <div className="flex items-start gap-5">
              {has('move') && (
                <div className="grid grid-cols-3 gap-1">
                  <span />
                  <button className={joyBtn} disabled={blocked} onClick={() => move('y', 1)} title="Y+" aria-label="Y+">
                    <ArrowUp size={16} />
                  </button>
                  <span />
                  <button className={joyBtn} disabled={blocked} onClick={() => move('x', -1)} title="X−" aria-label="X−">
                    <ArrowLeft size={16} />
                  </button>
                  {has('home') ? (
                    <button
                      className={homePadBtn}
                      disabled={blocked}
                      onClick={() => send('home')}
                      title={t('printers.prusaConnectLocal.controls.home')}
                      aria-label={t('printers.prusaConnectLocal.controls.home')}
                    >
                      <Home size={16} />
                    </button>
                  ) : (
                    <span />
                  )}
                  <button className={joyBtn} disabled={blocked} onClick={() => move('x', 1)} title="X+" aria-label="X+">
                    <ArrowRight size={16} />
                  </button>
                  <span />
                  <button className={joyBtn} disabled={blocked} onClick={() => move('y', -1)} title="Y−" aria-label="Y−">
                    <ArrowDown size={16} />
                  </button>
                  <span />
                </div>
              )}
              {has('move_z') && (
                <div className="flex flex-col items-center gap-1">
                  <button className={joyBtn} disabled={blocked} onClick={() => move('z', 1)} title="Z+" aria-label="Z+">
                    <ArrowUp size={16} />
                  </button>
                  <span className="h-10 flex items-center text-xs font-semibold text-[var(--text-muted)]">Z</span>
                  <button className={joyBtn} disabled={blocked} onClick={() => move('z', -1)} title="Z−" aria-label="Z−">
                    <ArrowDown size={16} />
                  </button>
                </div>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {has('home') && !has('move') && (
                <button className={`${actionBtn} flex items-center gap-1`} disabled={blocked} onClick={() => send('home')}>
                  <Home size={14} />
                  {t('printers.prusaConnectLocal.controls.home')}
                </button>
              )}
              {has('disable_steppers') && (
                <button className={actionBtn} disabled={blocked} onClick={() => send('disable_steppers')}>
                  {t('printers.prusaConnectLocal.controls.disableSteppers')}
                </button>
              )}
              {has('reset_printer') && (
                <button
                  className={dangerBtn}
                  disabled={blocked}
                  onClick={() => confirmAndSend(t('printers.prusaConnectLocal.controls.confirmReset'), 'reset_printer')}
                >
                  {t('printers.prusaConnectLocal.controls.resetPrinter')}
                </button>
              )}
            </div>
          </Section>
        )}

        <Section title={t('printers.prusaConnectLocal.controls.temperatures')}>
          <TemperatureRow
            label={[t('printers.prusaConnectLocal.controls.extruder'), activeTool?.material].filter(Boolean).join(' · ')}
            current={controls.temperatures.nozzle}
            target={controls.temperatures.nozzle_target}
            spec={argument(controls, 'set_nozzle_temperature', 'nozzle_temperature')}
            disabled={blocked || !has('set_nozzle_temperature')}
            onSet={(target) => send('set_nozzle_temperature', { nozzle_temperature: target })}
          />
          <TemperatureRow
            label={t('printers.prusaConnectLocal.controls.bed')}
            current={controls.temperatures.bed}
            target={controls.temperatures.bed_target}
            spec={argument(controls, 'set_bed_temperature', 'bed_temperature')}
            disabled={blocked || !has('set_bed_temperature')}
            onSet={(target) => send('set_bed_temperature', { bed_temperature: target })}
          />
        </Section>

        {(has('set_speed') || has('set_flow')) && (
          <Section title={t('printers.prusaConnectLocal.controls.speedAndFlow')}>
            {has('set_speed') && (
              <PercentControl
                label={t('printers.prusaConnectLocal.controls.speed')}
                value={controls.speed}
                spec={argument(controls, 'set_speed', 'speed')}
                disabled={blocked}
                onCommit={(speed) => send('set_speed', { speed })}
              />
            )}
            {has('set_flow') && (
              <PercentControl
                label={t('printers.prusaConnectLocal.controls.flow')}
                value={controls.flow}
                spec={argument(controls, 'set_flow', 'flow')}
                disabled={blocked}
                onCommit={(flow) => send('set_flow', { flow })}
              />
            )}
          </Section>
        )}

        {hasChamber && (
          <Section title={t('printers.prusaConnectLocal.controls.chamber')}>
            {has('set_chamber_fan_target') && (
              <div className="flex flex-col gap-2">
                <span className={labelClass}>{t('printers.prusaConnectLocal.controls.fan')}</span>
                <Segmented
                  label={t('printers.prusaConnectLocal.controls.fan')}
                  options={[
                    { value: 'off', label: t('printers.prusaConnectLocal.controls.fanOff') },
                    { value: 'auto', label: t('printers.prusaConnectLocal.controls.fanAuto') },
                    { value: 'manual', label: t('printers.prusaConnectLocal.controls.fanManual') },
                  ]}
                  value={chamberFan === null ? null : chamberFan === 0 ? 'off' : chamberFan < 0 ? 'auto' : 'manual'}
                  disabled={blocked}
                  onSelect={(mode) => {
                    if (mode === 'manual') {
                      setChamberFan(chamberFan !== null && chamberFan > 0 ? chamberFan : 50);
                      return;
                    }
                    const target = mode === 'off' ? 0 : -1;
                    setChamberFan(target);
                    send('set_chamber_fan_target', { 'chamber.fan_pwm_target': target });
                  }}
                />
                {chamberFan !== null && chamberFan > 0 && (
                  <PercentControl
                    label={t('printers.prusaConnectLocal.controls.fanSpeed')}
                    value={chamberFan}
                    spec={{ name: 'fan', minimum: 1, maximum: fanSpec?.maximum ?? 100 }}
                    disabled={blocked}
                    onCommit={(value) => {
                      setChamberFan(value);
                      send('set_chamber_fan_target', { 'chamber.fan_pwm_target': value });
                    }}
                  />
                )}
              </div>
            )}
            {has('set_chamber_led_intensity') && (
              <PercentControl
                label={t('printers.prusaConnectLocal.controls.light')}
                value={chamberLight}
                spec={argument(controls, 'set_chamber_led_intensity', 'chamber.led_intensity')}
                disabled={blocked}
                onCommit={(value) => {
                  setChamberLight(value);
                  send('set_chamber_led_intensity', { 'chamber.led_intensity': value });
                }}
              />
            )}
            <p className="text-[11px] leading-snug text-[var(--text-muted)]">{t('printers.prusaConnectLocal.controls.chamberHint')}</p>
          </Section>
        )}

        {controls.tools.length > 0 && hasNozzleSettings && (
          <Section title={t('printers.prusaConnectLocal.controls.nozzles')}>
            {controls.tools.map((tool) => (
              <div key={tool.index} className="flex flex-col gap-2">
                {controls.tools.length > 1 && (
                  <p className="text-sm font-medium">
                    {t('printers.prusaConnectLocal.controls.extruder')} {tool.index + 1}
                  </p>
                )}
                <div className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2">
                  {has('set_tool_nozzle_diameter') && (
                    <>
                      <span className={labelClass}>{t('printers.prusaConnectLocal.controls.diameter')}</span>
                      <select
                        aria-label={t('printers.prusaConnectLocal.controls.diameter')}
                        className="w-28 rounded px-2 py-1 text-sm bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent)]"
                        disabled={blocked}
                        value={tool.nozzle_diameter ?? ''}
                        onChange={(e) =>
                          send('set_tool_nozzle_diameter', { tool: tool.index, nozzle_diameter: Number(e.target.value) })
                        }
                      >
                        {tool.nozzle_diameter !== null && !NOZZLE_DIAMETERS.includes(tool.nozzle_diameter) && (
                          <option value={tool.nozzle_diameter}>{tool.nozzle_diameter} mm</option>
                        )}
                        {NOZZLE_DIAMETERS.map((diameter) => (
                          <option key={diameter} value={diameter}>
                            {diameter} mm
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                  {(['high_flow', 'hardened'] as const)
                    .filter((feature) => has(`set_tool_${feature}`))
                    .map((feature) => {
                      const label =
                        feature === 'high_flow'
                          ? t('printers.prusaConnectLocal.controls.highFlow')
                          : t('printers.prusaConnectLocal.controls.hardened');
                      return (
                        <div key={feature} className="contents">
                          <span className={labelClass}>{label}</span>
                          <Segmented
                            label={label}
                            options={onOff}
                            value={tool[feature]}
                            disabled={blocked}
                            onSelect={(on) => send(`set_tool_${feature}`, { tool: tool.index, [feature]: on })}
                          />
                        </div>
                      );
                    })}
                </div>
              </div>
            ))}
          </Section>
        )}

        <Section title={t('printers.prusaConnectLocal.controls.utilities')}>
          {(has('set_printer_ready') || has('set_idle')) && (
            <div className="flex flex-col gap-1.5">
              <span className={labelClass}>{t('printers.prusaConnectLocal.controls.state')}</span>
              <div className="flex flex-wrap gap-2">
                {has('set_printer_ready') && (
                  <button className={actionBtn} disabled={blocked || isReady} onClick={() => send('set_printer_ready')}>
                    {t('printers.prusaConnectLocal.controls.markReady')}
                  </button>
                )}
                {has('set_idle') && (
                  <button className={actionBtn} disabled={blocked} onClick={() => send('set_idle')}>
                    {t('printers.prusaConnectLocal.controls.exitToIdle')}
                  </button>
                )}
              </div>
            </div>
          )}
          {has('mesh_bed_leveling') && (
            <div className="flex flex-col gap-1.5">
              <span className={labelClass}>{t('printers.prusaConnectLocal.controls.calibration')}</span>
              <div>
                <button
                  className={actionBtn}
                  disabled={blocked}
                  onClick={() => confirmAndSend(t('printers.prusaConnectLocal.controls.confirmMbl'), 'mesh_bed_leveling')}
                >
                  {t('printers.prusaConnectLocal.controls.meshBedLeveling')}
                </button>
              </div>
            </div>
          )}
          {(has('beep') || has('set_hostname')) && (
            <div className="flex flex-col gap-1.5">
              <span className={labelClass}>{t('printers.prusaConnectLocal.controls.system')}</span>
              <div className="flex flex-wrap items-center gap-2">
                {has('beep') && (
                  <button className={actionBtn} disabled={blocked} onClick={() => send('beep')}>
                    {t('printers.prusaConnectLocal.controls.beep')}
                  </button>
                )}
                {has('set_hostname') && hostnameInput === null && (
                  <button className={actionBtn} disabled={blocked} onClick={() => setHostnameInput(controls.hostname ?? '')}>
                    {t('printers.prusaConnectLocal.controls.changeHostname')}
                  </button>
                )}
              </div>
              {has('set_hostname') && hostnameInput !== null && (
                <div className="flex items-center gap-2 min-w-0">
                  <input
                    type="text"
                    autoFocus
                    aria-label={t('printers.prusaConnectLocal.controls.hostname')}
                    className="flex-1 min-w-0 rounded px-2 py-1 text-sm bg-[var(--bg-primary)] border border-[var(--border-color)] focus:outline-none focus:border-[var(--accent)]"
                    maxLength={argument(controls, 'set_hostname', 'hostname')?.max_length ?? 35}
                    value={hostnameInput}
                    onChange={(e) => setHostnameInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Escape' && setHostnameInput(null)}
                  />
                  <button
                    className={actionBtn}
                    disabled={blocked || !hostnameInput.trim()}
                    onClick={() => {
                      send('set_hostname', { hostname: hostnameInput.trim() });
                      setHostnameInput(null);
                    }}
                  >
                    {t('printers.prusaConnectLocal.controls.set')}
                  </button>
                </div>
              )}
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <span className={labelClass}>{t('printers.prusaConnectLocal.controls.camera')}</span>
            <p className="text-sm">
              {controls.camera ? (
                <>
                  <Video size={14} className="inline mr-1.5 -mt-0.5 text-[var(--accent)]" />
                  {controls.camera.name}
                  <span className="text-xs text-[var(--text-muted)]">
                    {' · '}
                    {controls.camera.stream
                      ? t('printers.prusaConnectLocal.controls.cameraStream')
                      : t('printers.prusaConnectLocal.controls.cameraStills')}
                  </span>
                </>
              ) : (
                <span className="text-[var(--text-muted)]">{t('printers.prusaConnectLocal.controls.cameraMissing')}</span>
              )}
            </p>
            {controls.camera?.overridden && (
              <p className="text-[11px] leading-snug text-yellow-500">{t('printers.prusaConnectLocal.controls.cameraOverridden')}</p>
            )}
            <div>
              <button
                className={`${actionBtn} inline-flex items-center gap-1.5`}
                disabled={!canUpdate || detectCamera.isPending}
                onClick={() => detectCamera.mutate()}
              >
                {detectCamera.isPending && <Loader2 size={14} className="animate-spin" />}
                {t('printers.prusaConnectLocal.controls.detectCamera')}
              </button>
            </div>
          </div>
        </Section>
      </div>
    </div>
  );
}
