import { appAssetPath } from './assetPaths';
import { api, type PrintQueueItem, type Printer } from '../api/client';

const PRINTER_IMAGE_BASE = '/img/printers';
const DEFAULT_PRINTER_IMAGE = `${PRINTER_IMAGE_BASE}/default.png`;

const MODEL_IMAGE_ALIASES: Array<[RegExp, string]> = [
  [/^(?:x1e|x1e.*)$/, 'x1e'],
  [/^(?:x1c|x1carbon|x1.*carbon.*)$/, 'x1c'],
  [/^x1$/, 'x1c'],
  [/^(?:x2d|n6)$/, 'x2d'],
  [/^(?:a2l|n9|bambulaba2l)$/, 'a2l'],
  [/^h2dpro$/, 'h2dpro'],
  [/^h2d$/, 'h2d'],
  [/^h2c$/, 'h2c'],
  [/^h2s$/, 'h2d'],
  [/^o1c$/, 'o1c'],
  [/^o1e$/, 'o1e'],
  [/^o1s$/, 'o1s'],
  [/^p2s$/, 'p1s'],
  [/^p1s$/, 'p1s'],
  [/^p1p$/, 'p1p'],
  [/^a1mini$/, 'a1mini'],
  [/^a1f$/, 'a1f'],
  [/^a1$/, 'a1'],
  [/^elegooneptune3$/, 'elegoo-neptune-3'],
  [/^elegooneptune3pro$/, 'elegoo-neptune-3-pro'],
  [/^elegooneptune3plus$/, 'elegoo-neptune-3-plus'],
  [/^elegooneptune3max$/, 'elegoo-neptune-3-max'],
  [/^elegooneptune4$/, 'elegoo-neptune-4'],
  [/^elegooneptune4pro$/, 'elegoo-neptune-4-pro'],
  [/^elegooneptune4plus$/, 'elegoo-neptune-4-plus'],
  [/^elegooneptune4max$/, 'elegoo-neptune-4-max'],
  [/^elegoocentauricarbon$/, 'elegoo-centauri-carbon'],
  [/^crealityk2plus$/, 'creality-k2-plus'],
  [/^crealityk1c$/, 'creality-k1c'],
  [/^crealityk1$/, 'creality-k1'],
  [/^(?:snapmakeru1|u1)$/, 'snapmaker-u1'],
  [/^prusacoreone$/, 'prusa-core-one'],
  [/^prusamk4s$/, 'prusa-mk4s'],
  [/^prusamk4$/, 'prusa-mk4'],
  [/^prusamk39s$/, 'prusa-mk3.9S'],
  [/^prusamk39$/, 'prusa-mk3.9'],
  [/^prusamk35s$/, 'prusa-mk3.5S'],
  [/^prusamk35$/, 'prusa-mk3.5'],
  [/^prusaxl$/, 'prusa-xl'],
  [/^prusamini$/, 'prusa-mini+'],
  [/^prusamk3s$/, 'prusa-mk3s+'],
  [/^(?:klipper|prusalink|octoprint|genericklipperprinter|genericfdmprinter)$/, 'generic-printer'],
];

function normalizePrinterModel(model: string): string {
  return model.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function printerImagePath(filename: string): string {
  return appAssetPath(`${PRINTER_IMAGE_BASE}/${filename}`);
}

export function getDefaultPrinterImage(): string {
  return appAssetPath(DEFAULT_PRINTER_IMAGE);
}

export function getPrinterDisplayImage(printer: Pick<Printer, 'id' | 'model' | 'custom_image_filename'>): string {
  return printer.custom_image_filename
    ? api.getPrinterCustomImageUrl(printer.id, printer.custom_image_filename)
    : getPrinterImage(printer.model);
}

export function getPrinterImage(model: string | null | undefined): string {
  if (!model) return getDefaultPrinterImage();
  const normalizedModel = normalizePrinterModel(model);
  const imageKey = MODEL_IMAGE_ALIASES.find(([pattern]) => pattern.test(normalizedModel))?.[1];
  return imageKey ? printerImagePath(`${imageKey}.png`) : getDefaultPrinterImage();
}

// G-code interchange families (#2578). Mirrors backend GCODE_COMPAT_FAMILIES
// in backend/app/utils/printer_models.py — keep the two in sync. A sliced 3MF
// may target a different model ONLY within its family; everything else is
// exact-match only.
const GCODE_COMPAT_FAMILIES: ReadonlyArray<ReadonlySet<string>> = [
  new Set(['X1', 'X1C', 'X1E', 'P1P', 'P1S']),
];

/** True when G-code sliced for one model may be dispatched to the other.
 *  Unknown/missing metadata on either side returns true (can't validate). */
export function isGcodeCompatible(
  slicedForModel: string | null | undefined,
  targetModel: string | null | undefined,
): boolean {
  if (!slicedForModel || !targetModel) return true;
  const norm = (m: string) => m.trim().toUpperCase().replace(/[\s-]/g, '');
  const a = norm(slicedForModel);
  const b = norm(targetModel);
  if (a === b) return true;
  return GCODE_COMPAT_FAMILIES.some((family) => family.has(a) && family.has(b));
}

export function getWifiStrength(rssi: number): { labelKey: string; color: string; bars: number } {
  if (rssi >= -50) return { labelKey: 'printers.wifiSignal.excellent', color: 'text-bambu-green', bars: 4 };
  if (rssi >= -60) return { labelKey: 'printers.wifiSignal.good', color: 'text-bambu-green', bars: 3 };
  if (rssi >= -70) return { labelKey: 'printers.wifiSignal.fair', color: 'text-yellow-400', bars: 2 };
  if (rssi >= -80) return { labelKey: 'printers.wifiSignal.weak', color: 'text-orange-400', bars: 1 };
  return { labelKey: 'printers.wifiSignal.veryWeak', color: 'text-red-400', bars: 1 };
}

/**
 * Filters queue items based on printer compatibility (filament types and colors).
 * Mirrors backend _find_idle_printer_for_model() logic.
 * @param items - Array of queue items to filter
 * @param loadedFilamentTypes - Set of loaded filament types (e.g., "PLA", "PETG")
 * @param loadedFilaments - Set of loaded filament type+color pairs (e.g., "PLA:ffffff", "PETG:ff0000")
 * @param loadedVariants - Set of loaded type+color+tray_info_idx triples
 *   (e.g., "PLA:ffffff:GFA01"; the idx is "" for custom/third-party spools). Used to
 *   distinguish Bambu PLA sub-variants (Basic GFA00 / Matte GFA01 / Silk GFA06) that
 *   share a base type+colour, mirroring the backend _get_missing_force_color_slots (#2650).
 *   When omitted, force matching falls back to type+colour so the hint is never stricter
 *   than the data available.
 * @returns Array of compatible queue items
 */
export function filterCompatibleQueueItems(
  items: PrintQueueItem[],
  loadedFilamentTypes?: Set<string>,
  loadedFilaments?: Set<string>,
  loadedVariants?: Set<string>
): PrintQueueItem[] {
  return items.filter(item => {
    // Type check: all required filament types must be loaded
    if (item.required_filament_types && item.required_filament_types.length > 0 && loadedFilamentTypes !== undefined) {
      if (!item.required_filament_types.every((t: string) => loadedFilamentTypes.has(t.toUpperCase()))) {
        return false;
      }
    }

    // Color check: evaluate force_color_match per slot
    // Only apply when loadedFilaments is provided (not undefined).
    // An empty Set means no filaments are loaded — force-matched slots cannot match.
    if (item.filament_overrides && item.filament_overrides.length > 0 && loadedFilaments !== undefined) {
      const forceOverrides = item.filament_overrides.filter(o => o.force_color_match === true);
      const prefOverrides = item.filament_overrides.filter(o => o.force_color_match !== true);

      // All force-matched slots must have an exact type+color match — and, when the
      // override carries a tray_info_idx, the same variant too (a loaded tray with a
      // blank idx still satisfies it, matching the backend's type+colour fallback).
      if (forceOverrides.length > 0) {
        const allForceMatch = forceOverrides.every(o => {
          const oType = (o.type || '').toUpperCase();
          const oColor = (o.color || '').replace('#', '').toLowerCase().slice(0, 6);
          const oIdx = o.tray_info_idx || '';
          // No variant on the override, or no variant data supplied → type+colour only.
          if (!oIdx || loadedVariants === undefined) {
            return loadedFilaments.has(`${oType}:${oColor}`);
          }
          // Variant-specific: same idx, or a same-colour tray that reports no idx.
          return loadedVariants.has(`${oType}:${oColor}:${oIdx}`) || loadedVariants.has(`${oType}:${oColor}:`);
        });
        if (!allForceMatch) return false;
      }

      // Preference-only overrides: at least one color must match (existing behaviour)
      if (prefOverrides.length > 0 && forceOverrides.length === 0) {
        const hasColorMatch = prefOverrides.some(o => {
          const oType = (o.type || '').toUpperCase();
          const oColor = (o.color || '').replace('#', '').toLowerCase().slice(0, 6);
          return loadedFilaments.has(`${oType}:${oColor}`);
        });
        if (!hasColorMatch) return false;
      }
    }

    return true;
  });
}
