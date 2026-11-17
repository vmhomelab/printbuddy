import type { Printer } from '../../api/client';
import type { PrintOptions } from './types';

// Provider-gated Bambu print-start flags. The per-item preheat override is a
// scheduler stage and the post-print outcome prompt (#1898) is Printbuddy-side
// state, not firmware flags, so neither is part of this list.
export type PrintOptionKey = Exclude<
  keyof PrintOptions,
  'preheat_override' | 'preheat_chamber_target_override' | 'confirm_outcome'
>;

const ALL_PRINT_OPTIONS: PrintOptionKey[] = [
  'bed_levelling',
  'flow_cali',
  'vibration_cali',
  'layer_inspect',
  'timelapse',
  'nozzle_offset_cali',
];

const EMPTY_PRINT_OPTIONS: PrintOptionKey[] = [];

// "Disabled" value per key: tri-state calibration options use 'off', the
// rest are plain booleans.
const DISABLED_PRINT_OPTIONS: Pick<PrintOptions, PrintOptionKey> = {
  bed_levelling: 'off',
  flow_cali: 'off',
  vibration_cali: false,
  layer_inspect: false,
  timelapse: false,
  nozzle_offset_cali: 'off',
};

/**
 * Print start options are provider-specific command flags.
 * Bambu firmware understands these flags directly. Moonraker/Fluidd/Mainsail
 * and PrusaLink start already-sliced files through provider file/start APIs, so
 * Bambu calibration/AI/timelapse flags would be ignored or misleading there.
 */
export function getSupportedPrintOptionKeysForPrinter(
  printer: Pick<Printer, 'provider' | 'model'> | null | undefined
): PrintOptionKey[] {
  if (!printer?.provider) {
    return ALL_PRINT_OPTIONS;
  }

  return printer.provider === 'bambu' ? ALL_PRINT_OPTIONS : EMPTY_PRINT_OPTIONS;
}

export function getSharedSupportedPrintOptionKeys(
  printers: Array<Pick<Printer, 'provider' | 'model'>>
): PrintOptionKey[] {
  if (printers.length === 0) {
    return ALL_PRINT_OPTIONS;
  }

  return ALL_PRINT_OPTIONS.filter((key) =>
    printers.every((printer) => getSupportedPrintOptionKeysForPrinter(printer).includes(key))
  );
}

export function sanitizePrintOptionsForPrinter(
  options: PrintOptions,
  printer: Pick<Printer, 'provider' | 'model'> | null | undefined
): PrintOptions {
  const supportedKeys = getSupportedPrintOptionKeysForPrinter(printer);
  const sanitized: PrintOptions = { ...options, ...DISABLED_PRINT_OPTIONS };
  for (const key of supportedKeys) {
    (sanitized as Record<PrintOptionKey, unknown>)[key] = options[key];
  }
  return sanitized;
}
