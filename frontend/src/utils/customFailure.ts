import type { TFunction } from 'i18next';
import type { CustomFailureMaterial, CustomFailureReason } from '../api/client';
import { parseUTCDate } from './date';

/** Translated default text of a default reason ("fail_reason_08"), or '' if there is none. */
function defaultReasonText(t: TFunction, code: string, part: 'title' | 'subtitle'): string {
  return t(`customFailure.reasons.${code}.${part}`, { defaultValue: '' });
}

/** Bold title of a reason: own text if typed in the settings, else the translated default, else the code. */
export function customFailureReasonTitle(t: TFunction, code: string, reason?: CustomFailureReason): string {
  return reason?.title || defaultReasonText(t, code, 'title') || code;
}

/** Subtitle (examples) of a reason, or ''. */
export function customFailureReasonSubtitle(t: TFunction, code: string, reason?: CustomFailureReason): string {
  return reason?.subtitle || defaultReasonText(t, code, 'subtitle');
}

/** "As square as possible": columns = ceil(sqrt(n)), capped by how many tiles fit the screen. */
export function reasonGridColumns(count: number, availableWidth: number, minTileWidth = 150): number {
  const square = Math.max(1, Math.ceil(Math.sqrt(count)));
  const fitting = Math.max(1, Math.floor(availableWidth / minTileWidth));
  return Math.min(square, fitting);
}

/** Local date as YYYY-MM-DD. */
export function formatIsoDay(dateStr: string | null | undefined): string {
  const date = parseUTCDate(dateStr);
  if (!date) return '–';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Accepts "#FFFFFF", "FFFFFF" or 8-digit RGBA ("FFFFFFFF") and returns "#RRGGBB", or null. */
export function normalizeFilamentColor(color: string | null | undefined): string | null {
  const hex = (color ?? '').trim().replace(/^#/, '');
  if (!/^[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(hex)) return null;
  return `#${hex.slice(0, 6).toUpperCase()}`;
}

/** Total grams: the report's total, or the sum of the per-material amounts. */
export function totalMaterialGrams(materials: CustomFailureMaterial[], total: number | null): number | null {
  if (total != null) return total;
  const known = materials.filter((m) => m.grams != null);
  return known.length ? known.reduce((sum, m) => sum + (m.grams ?? 0), 0) : null;
}

export function formatGrams(grams: number | null | undefined): string {
  if (grams == null) return '–';
  return `${grams >= 100 ? Math.round(grams) : grams.toFixed(1)} g`;
}
