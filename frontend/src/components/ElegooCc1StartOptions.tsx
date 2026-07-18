import type { ElegooCc1StartOptionsValue, ElegooPrintPlatformType } from '../utils/elegooCc1';

interface ElegooCc1StartOptionsProps {
  value: ElegooCc1StartOptionsValue;
  onChange: (value: ElegooCc1StartOptionsValue) => void;
  compact?: boolean;
}

export function ElegooCc1StartOptions({ value, onChange, compact = false }: ElegooCc1StartOptionsProps) {
  const setBedLevelling = (bed_levelling: boolean) => onChange({ ...value, bed_levelling });
  const setPrintPlatformType = (print_platform_type: ElegooPrintPlatformType) => onChange({ ...value, print_platform_type });

  return (
    <div className={compact ? 'space-y-3' : 'rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/40 p-4 space-y-4'}>
      {!compact && <h3 className="text-sm font-semibold text-white">Elegoo CC1 Start Options</h3>}
      <label className="flex items-center gap-3 text-sm text-white cursor-pointer">
        <input
          type="checkbox"
          checked={value.bed_levelling}
          onChange={(event) => setBedLevelling(event.target.checked)}
          className="h-4 w-4 rounded border-bambu-dark-tertiary bg-bambu-dark text-bambu-green focus:ring-bambu-green"
        />
        <span>Heated Bed Leveling</span>
      </label>

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => setPrintPlatformType(0)}
          className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
            value.print_platform_type === 0
              ? 'border-bambu-green bg-bambu-green/20 text-white'
              : 'border-bambu-dark-tertiary bg-bambu-dark text-bambu-gray hover:text-white'
          }`}
        >
          <span className="block font-medium">Textured Build Plate</span>
          <span className="text-xs text-bambu-gray">Side A</span>
        </button>
        <button
          type="button"
          onClick={() => setPrintPlatformType(1)}
          className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
            value.print_platform_type === 1
              ? 'border-bambu-green bg-bambu-green/20 text-white'
              : 'border-bambu-dark-tertiary bg-bambu-dark text-bambu-gray hover:text-white'
          }`}
        >
          <span className="block font-medium">Smooth Build Plate</span>
          <span className="text-xs text-bambu-gray">Side B</span>
        </button>
      </div>
    </div>
  );
}
