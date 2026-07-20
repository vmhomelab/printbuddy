import type { PrinterProvider } from '../api/client';

export type ElegooPrintPlatformType = 0 | 1;

export interface ElegooCc1StartOptionsValue {
  bed_levelling: boolean;
  print_platform_type: ElegooPrintPlatformType;
}

export function isElegooCc1Printer(provider?: PrinterProvider | null, model?: string | null): boolean {
  return provider === 'elegoo_sdcp' && (model || '').toLowerCase().includes('centauri');
}
