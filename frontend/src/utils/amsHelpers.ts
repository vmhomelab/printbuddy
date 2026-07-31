/**
 * AMS (Automatic Material System) helper utilities for Bambu Lab printers.
 * These functions handle color normalization, slot labeling, and tray ID calculations
 * for AMS, AMS-HT, and external spool configurations.
 */
import type { AMSTray, AMSUnit, InventorySpool, Printer, PrinterStatus, SpoolAssignment } from '../api/client';
import { parseUTCDate } from './date';

/**
 * Normalize color format from various sources.
 * API returns "RRGGBBAA" (8-char), 3MF uses "#RRGGBB" (7-char with hash).
 * This normalizes to "#RRGGBB" format.
 */
export function normalizeColor(color: string | null | undefined): string {
  if (!color) return '#808080';
  // Remove alpha channel if present (8-char hex to 6-char)
  const hex = color.replace('#', '').substring(0, 6);
  return `#${hex}`;
}

/**
 * Normalize color for comparison (case-insensitive, strip hash and alpha).
 */
export function normalizeColorForCompare(color: string | undefined): string {
  if (!color) return '';
  return color.replace('#', '').toLowerCase().substring(0, 6);
}

/**
 * Filament type equivalence groups.
 * Types within the same group are interchangeable on the printer side
 * (e.g., Bambu Lab firmware treats PA-CF and PA12-CF as compatible).
 */
const FILAMENT_TYPE_GROUPS: string[][] = [
  ['PA-CF', 'PA12-CF', 'PAHT-CF'],
];

const _equivalenceMap: Record<string, string> = {};
for (const group of FILAMENT_TYPE_GROUPS) {
  const canonical = group[0];
  for (const t of group) {
    _equivalenceMap[t.toUpperCase()] = canonical.toUpperCase();
  }
}

/**
 * Get the canonical filament type for equivalence matching.
 * Types in the same group (e.g., PA-CF / PA12-CF / PAHT-CF) return the same canonical type.
 */
export function canonicalFilamentType(type: string | undefined): string {
  if (!type) return '';
  const upper = type.toUpperCase();
  return _equivalenceMap[upper] ?? upper;
}

/**
 * Check if two filament types are compatible (same type or same equivalence group).
 */
export function filamentTypesCompatible(a: string | undefined, b: string | undefined): boolean {
  return canonicalFilamentType(a) === canonicalFilamentType(b);
}

/**
 * Check if two colors are visually similar within a threshold.
 * Uses RGB component comparison with configurable tolerance.
 * @param color1 - First hex color
 * @param color2 - Second hex color
 * @param threshold - Maximum difference per RGB component (default: 40)
 */
export function colorsAreSimilar(
  color1: string | undefined,
  color2: string | undefined,
  threshold = 40
): boolean {
  const hex1 = normalizeColorForCompare(color1);
  const hex2 = normalizeColorForCompare(color2);
  if (!hex1 || !hex2 || hex1.length < 6 || hex2.length < 6) return false;

  const r1 = parseInt(hex1.substring(0, 2), 16);
  const g1 = parseInt(hex1.substring(2, 4), 16);
  const b1 = parseInt(hex1.substring(4, 6), 16);
  const r2 = parseInt(hex2.substring(0, 2), 16);
  const g2 = parseInt(hex2.substring(2, 4), 16);
  const b2 = parseInt(hex2.substring(4, 6), 16);

  return (
    Math.abs(r1 - r2) <= threshold &&
    Math.abs(g1 - g2) <= threshold &&
    Math.abs(b1 - b2) <= threshold
  );
}

/**
 * Format slot label for display in the UI.
 * @param amsId - AMS unit ID (0-3 for regular AMS, 128+ for AMS-HT)
 * @param trayId - Tray/slot ID within the AMS unit (0-3)
 * @param isHt - Whether this is an AMS-HT unit (single tray)
 * @param isExternal - Whether this is the external spool holder
 */
export function formatSlotLabel(
  amsId: number,
  trayId: number,
  isHt: boolean,
  isExternal: boolean
): string {
  if (isExternal) return 'Ext';
  // Convert AMS ID to letter (A, B, C, D)
  // AMS-HT uses IDs starting at 128
  const letter = String.fromCharCode(65 + (amsId >= 128 ? amsId - 128 : amsId));
  if (isHt) return `HT-${letter}`;
  return `${letter}${trayId + 1}`;
}

/**
 * Calculate global tray ID for MQTT command.
 * Used in the ams_mapping array sent to the printer.
 * @param amsId - AMS unit ID (0-3 for regular AMS, 128+ for AMS-HT)
 * @param trayId - Tray/slot ID within the AMS unit
 * @param isExternal - Whether this is the external spool holder
 * @returns Global tray ID (0-15 for AMS, 128+ for AMS-HT, 254 for external)
 */
export function getGlobalTrayId(
  amsId: number,
  trayId: number,
  isExternal: boolean
): number {
  if (isExternal) return 254 + trayId;
  // AMS-HT units have IDs starting at 128 with a single tray — use ID directly
  if (amsId >= 128) return amsId;
  return amsId * 4 + trayId;
}

/**
 * Get fill bar color based on spool fill level.
 * Matches PrintersPage thresholds and Bambu Lab brand green.
 */
export function getFillBarColor(fillLevel: number): string {
  if (fillLevel > 50) return '#00ae42'; // Green - good
  if (fillLevel >= 15) return '#f59e0b'; // Amber - warning (<= 50%)
  return '#ef4444'; // Red - critical (< 15%)
}

/**
 * Calculate fill level from Spoolman weight data.
 * Used as the first source in the Spoolman → Inventory → AMS fill chain.
 */
export function getSpoolmanFillLevel(
  linkedSpool: { remaining_weight: number | null; filament_weight: number | null } | undefined
): number | null {
  if (!linkedSpool?.remaining_weight || !linkedSpool?.filament_weight
      || linkedSpool.filament_weight <= 0) return null;
  return Math.min(100, Math.round(
    (linkedSpool.remaining_weight / linkedSpool.filament_weight) * 100
  ));
}

function toFixedHex(value: number, width: number): string {
  const safe = Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0;
  return safe.toString(16).toUpperCase().padStart(width, '0').slice(-width);
}

// 32-bit FNV-1a hash -> 8-char hex (stable for alphanumeric serials)
function hashSerialToHex32(serial: string): string {
  const input = (serial || '').trim().toUpperCase();
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).toUpperCase().padStart(8, '0');
}

/**
 * Generate a stable fallback spool tag for slots without RFID identifiers.
 * Returns a 16-char hex string derived from the printer serial + slot position.
 */
export function getFallbackSpoolTag(printerSerial: string, amsId: number, trayId: number): string {
  return `${hashSerialToHex32(printerSerial)}${toFixedHex(amsId, 4)}${toFixedHex(trayId, 4)}`;
}

/**
 * Get minimum datetime for scheduling (now + 1 minute).
 * Returns ISO string format for datetime-local input.
 */
export function getMinDateTime(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() + 1);
  return now.toISOString().slice(0, 16);
}

/**
 * Check if a scheduled time is a placeholder far-future date.
 * Placeholder dates (more than 6 months out) are treated as ASAP.
 */
export function isPlaceholderDate(scheduledTime: string | null | undefined): boolean {
  if (!scheduledTime) return false;
  const sixMonthsFromNow = Date.now() + 180 * 24 * 60 * 60 * 1000;
  return (parseUTCDate(scheduledTime)?.getTime() ?? 0) > sixMonthsFromNow;
}

/**
 * Auto-match a filament requirement to a loaded filament, respecting nozzle constraints.
 * Used by both single-printer (FilamentMapping) and multi-printer (InlineMappingEditor) paths.
 */
export function autoMatchFilament(
  req: { type?: string; color?: string; nozzle_id?: number | null },
  loadedFilaments: { globalTrayId: number; type?: string; color?: string; extruderId?: number; remain?: number }[],
  usedTrayIds: Set<number>,
  preferLowest?: boolean,
): typeof loadedFilaments[number] | undefined {
  let nozzleFilaments = filterFilamentsByNozzle(loadedFilaments, req.nozzle_id);

  if (preferLowest) {
    nozzleFilaments = [...nozzleFilaments].sort((a, b) => {
      const ra = (a.remain ?? -1) >= 0 ? (a.remain ?? -1) : 101;
      const rb = (b.remain ?? -1) >= 0 ? (b.remain ?? -1) : 101;
      return ra - rb;
    });
  }

  const exactMatch = nozzleFilaments.find(
    (f) =>
      !usedTrayIds.has(f.globalTrayId) &&
      filamentTypesCompatible(f.type, req.type) &&
      normalizeColorForCompare(f.color) === normalizeColorForCompare(req.color)
  );
  const similarMatch = exactMatch
    ? undefined
    : nozzleFilaments.find(
        (f) =>
          !usedTrayIds.has(f.globalTrayId) &&
          filamentTypesCompatible(f.type, req.type) &&
          colorsAreSimilar(f.color, req.color)
      );
  const typeOnlyMatch =
    exactMatch || similarMatch
      ? undefined
      : nozzleFilaments.find(
          (f) => !usedTrayIds.has(f.globalTrayId) && filamentTypesCompatible(f.type, req.type)
        );
  return exactMatch ?? similarMatch ?? typeOnlyMatch;
}

/**
 * Filter loaded filaments to those valid for a given nozzle requirement.
 * For single-nozzle printers (nozzle_id is null/undefined), returns all filaments.
 */
export function filterFilamentsByNozzle<T extends { extruderId?: number }>(
  loadedFilaments: T[],
  nozzleId: number | undefined | null,
): T[] {
  return loadedFilaments.filter(
    (f) => nozzleId == null || f.extruderId === nozzleId
  );
}

/**
 * Detect Bambu Lab RFID-tagged spool by tray_uuid (32 hex) or tag_uid (16 hex).
 *
 * Permissive zero-string check: any non-zero non-empty value returns true. The
 * function exists to suppress assign/unassign actions on RFID-managed slots
 * whose state is owned by the printer firmware — manual changes there would be
 * overwritten on the next RFID re-read (eye → pen icon in BambuStudio).
 */
export function isBambuLabSpool(tray: {
  tray_uuid?: string | null;
  tag_uid?: string | null;
} | null | undefined): boolean {
  if (!tray) return false;
  if (tray.tray_uuid && tray.tray_uuid !== '00000000000000000000000000000000') return true;
  if (tray.tag_uid && tray.tag_uid !== '0000000000000000') return true;
  return false;
}

export interface SpoolmanSlotAssignmentLike {
  printer_id: number;
  printer_name?: string | null;
  ams_id: number;
  tray_id: number;
  spoolman_spool_id: number;
  ams_label?: string | null;
}

export interface ResolvedLoadedFilamentInfo {
  material: string;
  detail: string;
  color?: string | null;
  remainingPct?: number | null;
  source: 'spoolman' | 'inventory' | 'telemetry';
  amsId: number;
  trayId: number;
  globalTrayId: number;
  tray?: AMSTray | null;
  spool?: InventorySpool | null;
}

export interface ResolveLoadedFilamentInfoInput {
  printer: Pick<Printer, 'id' | 'serial_number'>;
  status?: PrinterStatus;
  localAssignments?: SpoolAssignment[];
  getLocalAssignment?: (printerId: number, amsId: number, trayId: number) => SpoolAssignment | undefined;
  spoolmanSpools: InventorySpool[];
  spoolmanSlotAssignments: SpoolmanSlotAssignmentLike[];
}

function spoolLabel(spool: InventorySpool): string {
  return [spool.brand, spool.material, spool.subtype, spool.color_name].filter(Boolean).join(' ');
}

function spoolRemainingPct(spool: InventorySpool): number | null {
  if (!spool.label_weight || spool.label_weight <= 0) return null;
  return Math.round((Math.max(0, spool.label_weight - (spool.weight_used ?? 0)) / spool.label_weight) * 100);
}

function trayLabel(amsId: number, trayId: number, ams?: AMSUnit | null): string {
  if (amsId === -1) return 'Loaded spool';
  if (amsId === 255) return 'External spool';
  return `${ams?.is_ams_ht ? 'AMS-HT' : 'AMS'} ${amsId} tray ${trayId}`;
}

function trayMaterial(tray: AMSTray | null | undefined, fallback: string): string {
  if (!tray) return fallback;
  return [tray.tray_type, tray.tray_sub_brands].filter(Boolean).join(' ') || fallback;
}

function findTrayBySlot(ams: AMSUnit, trayId: number): AMSTray | undefined {
  return ams.tray.find((tray) => tray.id === trayId) ?? ams.tray[trayId];
}

function activeSlotCandidates(status?: PrinterStatus): Array<{ amsId: number; trayId: number; globalTrayId: number; ams?: AMSUnit; tray?: AMSTray }> {
  if (!status) return [];
  const trayNow = status.tray_now;
  const candidates: Array<{ amsId: number; trayId: number; globalTrayId: number; ams?: AMSUnit; tray?: AMSTray }> = [];

  for (const ams of status.ams ?? []) {
    for (const tray of ams.tray ?? []) {
      const trayId = tray.id ?? 0;
      const globalTrayId = getGlobalTrayId(ams.id, trayId, false);
      if (globalTrayId === trayNow) {
        candidates.push({ amsId: ams.id, trayId, globalTrayId, ams, tray });
      }
    }
    if (ams.id >= 128 && ams.id === trayNow && !candidates.some((candidate) => candidate.amsId === ams.id)) {
      const tray = findTrayBySlot(ams, 0);
      candidates.push({ amsId: ams.id, trayId: tray?.id ?? 0, globalTrayId: ams.id, ams, tray });
    }
  }

  for (const vt of status.vt_tray ?? []) {
    const globalTrayId = vt.id ?? 254;
    const trayId = globalTrayId >= 254 ? globalTrayId - 254 : 0;
    if (trayNow === globalTrayId || (trayNow === 254 && globalTrayId === 254)) {
      candidates.push({ amsId: 255, trayId, globalTrayId, tray: vt });
    }
  }

  return candidates;
}

function fallbackSlotCandidates(status?: PrinterStatus): Array<{ amsId: number; trayId: number; globalTrayId: number; ams?: AMSUnit; tray?: AMSTray }> {
  if (!status) return [];
  const candidates: Array<{ amsId: number; trayId: number; globalTrayId: number; ams?: AMSUnit; tray?: AMSTray }> = [];

  for (const vt of status.vt_tray ?? []) {
    if (vt.tray_type || vt.tray_sub_brands || vt.tray_color) {
      const globalTrayId = vt.id ?? 254;
      candidates.push({ amsId: 255, trayId: globalTrayId >= 254 ? globalTrayId - 254 : 0, globalTrayId, tray: vt });
    }
  }
  for (const ams of status.ams ?? []) {
    for (const tray of ams.tray ?? []) {
      if (tray.tray_type || tray.tray_sub_brands || tray.tray_color) {
        const trayId = tray.id ?? 0;
        candidates.push({ amsId: ams.id, trayId, globalTrayId: getGlobalTrayId(ams.id, trayId, false), ams, tray });
      }
    }
  }

  return candidates;
}

/**
 * Resolve the currently loaded/active filament for printer cards and TV mode.
 *
 * The regular printer card already derives the active slot from `tray_now` and
 * then overlays local/Spoolman assignment data. This helper centralises that
 * behaviour so compact surfaces such as Print Farm Monitor do not fall back to
 * the first populated AMS tray when an active AMS/AMS-HT/CFS slot assignment is
 * available.
 */
export function resolveLoadedFilamentInfo({
  printer,
  status,
  localAssignments = [],
  getLocalAssignment,
  spoolmanSpools,
  spoolmanSlotAssignments,
}: ResolveLoadedFilamentInfoInput): ResolvedLoadedFilamentInfo | null {
  const slotCandidates = [...activeSlotCandidates(status), ...fallbackSlotCandidates(status)];
  const seen = new Set<string>();

  for (const candidate of slotCandidates) {
    const key = `${candidate.amsId}:${candidate.trayId}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const spoolmanAssignment = spoolmanSlotAssignments.find((assignment) => (
      assignment.printer_id === printer.id && assignment.ams_id === candidate.amsId && assignment.tray_id === candidate.trayId
    ));
    const spoolmanSpool = spoolmanAssignment
      ? spoolmanSpools.find((spool) => spool.id === spoolmanAssignment.spoolman_spool_id)
      : undefined;
    if (spoolmanSpool) {
      return {
        material: spoolLabel(spoolmanSpool),
        detail: trayLabel(candidate.amsId, candidate.trayId, candidate.ams),
        color: spoolmanSpool.rgba,
        remainingPct: spoolRemainingPct(spoolmanSpool),
        source: 'spoolman',
        amsId: candidate.amsId,
        trayId: candidate.trayId,
        globalTrayId: candidate.globalTrayId,
        tray: candidate.tray ?? null,
        spool: spoolmanSpool,
      };
    }

    const localAssignment = getLocalAssignment?.(printer.id, candidate.amsId, candidate.trayId)
      ?? localAssignments.find((assignment) => (
        assignment.printer_id === printer.id && assignment.ams_id === candidate.amsId && assignment.tray_id === candidate.trayId
      ));
    if (localAssignment?.spool) {
      return {
        material: spoolLabel(localAssignment.spool),
        detail: trayLabel(candidate.amsId, candidate.trayId, candidate.ams),
        color: localAssignment.spool.rgba,
        remainingPct: spoolRemainingPct(localAssignment.spool),
        source: 'inventory',
        amsId: candidate.amsId,
        trayId: candidate.trayId,
        globalTrayId: candidate.globalTrayId,
        tray: candidate.tray ?? null,
        spool: localAssignment.spool,
      };
    }

    if (candidate.tray?.tray_type || candidate.tray?.tray_sub_brands || candidate.tray?.tray_color) {
      return {
        material: trayMaterial(candidate.tray, candidate.amsId === 255 ? 'External filament' : trayLabel(candidate.amsId, candidate.trayId, candidate.ams)),
        detail: trayLabel(candidate.amsId, candidate.trayId, candidate.ams),
        color: candidate.tray.tray_color,
        remainingPct: typeof candidate.tray.remain === 'number' && candidate.tray.remain >= 0 ? candidate.tray.remain : null,
        source: 'telemetry',
        amsId: candidate.amsId,
        trayId: candidate.trayId,
        globalTrayId: candidate.globalTrayId,
        tray: candidate.tray,
        spool: null,
      };
    }
  }

  const loadedLocalAssignment = getLocalAssignment?.(printer.id, -1, 0)
    ?? localAssignments.find((assignment) => assignment.printer_id === printer.id && assignment.ams_id === -1 && assignment.tray_id === 0);
  if (loadedLocalAssignment?.spool) {
    return {
      material: spoolLabel(loadedLocalAssignment.spool),
      detail: 'Loaded spool',
      color: loadedLocalAssignment.spool.rgba,
      remainingPct: spoolRemainingPct(loadedLocalAssignment.spool),
      source: 'inventory',
      amsId: -1,
      trayId: 0,
      globalTrayId: -1,
      tray: null,
      spool: loadedLocalAssignment.spool,
    };
  }

  const loadedSpoolmanAssignment = spoolmanSlotAssignments.find((assignment) => assignment.printer_id === printer.id && assignment.ams_id === 255 && assignment.tray_id === 0);
  const loadedSpoolman = loadedSpoolmanAssignment ? spoolmanSpools.find((spool) => spool.id === loadedSpoolmanAssignment.spoolman_spool_id) : undefined;
  if (loadedSpoolman) {
    return {
      material: spoolLabel(loadedSpoolman),
      detail: 'Loaded spool',
      color: loadedSpoolman.rgba,
      remainingPct: spoolRemainingPct(loadedSpoolman),
      source: 'spoolman',
      amsId: 255,
      trayId: 0,
      globalTrayId: 254,
      tray: null,
      spool: loadedSpoolman,
    };
  }

  return null;
}
