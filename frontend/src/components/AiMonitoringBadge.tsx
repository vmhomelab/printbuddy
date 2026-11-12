import { AlertTriangle, Loader2, ScanEye } from 'lucide-react';

export type AiMonitoringBadgeState = 'unavailable' | 'misconfigured' | 'enabled' | 'disabled';

const STATE_CLASSES: Record<AiMonitoringBadgeState, string> = {
  unavailable: 'border-gray-600 bg-gray-800/60 text-bambu-gray hover:text-white',
  misconfigured: 'border-amber-500/60 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20',
  enabled: 'border-bambu-green/60 bg-bambu-green/10 text-bambu-green hover:bg-bambu-green/20',
  disabled: 'border-gray-600 bg-gray-800/60 text-bambu-gray hover:text-white',
};

interface AiMonitoringBadgeProps {
  state: AiMonitoringBadgeState;
  /** Short state text, e.g. "AI On". */
  label: string;
  /** Detection provider shown next to the label (e.g. "Obico"); omitted when no provider is active. */
  provider?: string;
  title: string;
  pending?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

/** Per-printer AI failure-detection pill on the printer card, one per active provider. */
export function AiMonitoringBadge({ state, label, provider, title, pending, disabled, onClick }: AiMonitoringBadgeProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      data-provider={provider}
      className={`inline-flex h-6 flex-shrink-0 items-center gap-1 rounded-full border px-2 text-[11px] font-semibold leading-none transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${STATE_CLASSES[state]}`}
    >
      {pending ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : state === 'misconfigured' ? (
        <AlertTriangle className="h-3 w-3" />
      ) : (
        <ScanEye className="h-3 w-3" />
      )}
      <span className="hidden sm:inline">
        {label}
        {provider && <span className="font-normal opacity-80"> · {provider}</span>}
      </span>
      <span className="sm:hidden">AI</span>
    </button>
  );
}
