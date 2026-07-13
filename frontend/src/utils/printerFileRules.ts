import type { PrinterProvider } from '../api/client';

export interface PrinterFileRuleSet {
  accept: string;
  extensions: string[];
  descriptionExtensions: string;
}

const DEFAULT_RULES: PrinterFileRuleSet = {
  accept: '.gcode,.gco,.g',
  extensions: ['.gcode', '.gco', '.g'],
  descriptionExtensions: '.gcode, .gco, .g',
};

const RULES_BY_PROVIDER: Partial<Record<PrinterProvider, PrinterFileRuleSet>> = {
  bambu: {
    accept: '.3mf,.gcode.3mf',
    extensions: ['.3mf', '.gcode.3mf'],
    descriptionExtensions: '.3mf, .gcode.3mf',
  },
  klipper: DEFAULT_RULES,
  mainsail: DEFAULT_RULES,
  fluidd: DEFAULT_RULES,
  elegoo_sdcp: DEFAULT_RULES,
  prusalink: {
    accept: '.bgcode,.gcode,.gco,.g',
    extensions: ['.bgcode', '.gcode', '.gco', '.g'],
    descriptionExtensions: '.bgcode, .gcode, .gco, .g',
  },
};

export const getPrinterFileRuleSet = (provider?: PrinterProvider | null): PrinterFileRuleSet => {
  if (!provider) return DEFAULT_RULES;
  return RULES_BY_PROVIDER[provider] ?? DEFAULT_RULES;
};

export const isPrintableForProvider = (filename: string, provider?: PrinterProvider | null): boolean => {
  const lower = filename.toLowerCase();
  return getPrinterFileRuleSet(provider).extensions.some((extension) => lower.endsWith(extension));
};
