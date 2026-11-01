import { PRINTER_MODEL_GROUPS } from './printerModels';

const normalize = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, '');

/** Map a Prusa Connect Local model name (e.g. "CoreOne", "MK4S", "MINI") to a Printbuddy model value. */
export function mapPrusaConnectLocalModel(model: string | null | undefined, vendor?: string | null): string {
  const raw = (model || '').trim();
  if (!raw) return '';
  const prusaGroup = PRINTER_MODEL_GROUPS.find((group) => group.label === 'Prusa');
  const target = normalize(raw).replace(/^prusa/, '');
  const match = prusaGroup?.options.find((option) => {
    const label = normalize(option.label);
    return label === target || label === `${target}plus` || label.replace(/plus$/, '') === target;
  });
  if (match) return match.value;
  if ((vendor || '').toLowerCase() === 'prusa' && !raw.toLowerCase().startsWith('prusa')) {
    return `Prusa ${raw}`;
  }
  return raw;
}
