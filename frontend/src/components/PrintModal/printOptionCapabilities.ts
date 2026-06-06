import type { Printer } from '../../api/client';
import type { PrintOptions } from './types';

export type PrintOptionKey = keyof PrintOptions;

const ALL_PRINT_OPTIONS: PrintOptionKey[] = [
  'bed_levelling',
  'flow_cali',
  'vibration_cali',
  'layer_inspect',
  'timelapse',
];

const EMPTY_PRINT_OPTIONS: PrintOptionKey[] = [];

const EMPTY_PRINT_OPTIONS_VALUE: PrintOptions = {
  bed_levelling: false,
  flow_cali: false,
  vibration_cali: false,
  layer_inspect: false,
  timelapse: false,
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
  if (supportedKeys.length === 0) {
    return EMPTY_PRINT_OPTIONS_VALUE;
  }

  return ALL_PRINT_OPTIONS.reduce<PrintOptions>((acc, key) => {
    acc[key] = supportedKeys.includes(key) ? options[key] : false;
    return acc;
  }, { ...EMPTY_PRINT_OPTIONS_VALUE });
}
