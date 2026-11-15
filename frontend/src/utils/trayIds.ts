/**
 * H3C tray numbering (ported from upstream 1.3.1, #3442; mirrors
 * backend/app/utils/tray_ids.py).
 *
 * The H3C's AMS 3H is one unit (id 32, AMS type 6) with nine slots, numbered
 * 28 + slot as in Bambu Studio. Each of its nine hotends also has its own
 * external input, vir_slot 247-255, stored as (255, 0-8): 0 = 254, 1 = 255,
 * 2-8 = 247-253. Input v feeds hotend 255 - v, shown as "Ext-n".
 *
 * Unit 32 and the inputs 247-253 exist only on an H3C, so these helpers are
 * the H3C branch of the usual `ams_id * 4 + slot` arithmetic and change
 * nothing for any other printer.
 */

export const AMS3H_UNIT_ID = 32;
export const AMS3H_TYPE = 6;
export const AMS3H_TRAY_BASE = 28;
export const RACK_SLOT_COUNT = 9;
export const RACK_EXTERNAL_MIN = 247;

interface AmsUnitLike {
  id: number;
  ams_type?: number | null;
  module_type?: string;
  tray?: unknown[];
}

/** Whether an AMS unit is the H3C's AMS 3H. */
export function isAms3hUnit(unit: AmsUnitLike | null | undefined): boolean {
  if (!unit) return false;
  if (unit.ams_type === AMS3H_TYPE || unit.module_type === 'n10a') return true;
  return unit.id === AMS3H_UNIT_ID && (unit.tray?.length ?? 0) > 4;
}

/** Whether a model is an H3C (display name or model code N10). */
export function isH3cModel(model: string | null | undefined): boolean {
  const key = (model || '').toUpperCase().replace(/[\s-]/g, '');
  return key === 'H3C' || key === 'N10';
}

/** Global tray id of AMS 3H slot `slot` (0-8): 28 + slot. */
export function ams3hGlobalTrayId(slot: number): number {
  return AMS3H_TRAY_BASE + slot;
}

/** The AMS 3H slot (0-8) of global tray `trayId`, else null. */
export function ams3hSlotOf(trayId: number | null | undefined): number | null {
  if (typeof trayId !== 'number') return null;
  const slot = trayId - AMS3H_TRAY_BASE;
  return slot >= 0 && slot < RACK_SLOT_COUNT ? slot : null;
}

/** The tray_id an external input is stored under: 254 -> 0, 255 -> 1, 247-253 -> 2-8. */
export function externalSlotIndex(trayId: number): number {
  if (trayId === 254 || trayId === 255) return trayId - 254;
  return trayId - RACK_EXTERNAL_MIN + 2;
}

/** The global tray id of the external input stored as (255, slotIndex). */
export function externalTrayId(slotIndex: number): number {
  if (slotIndex === 0 || slotIndex === 1) return 254 + slotIndex;
  return RACK_EXTERNAL_MIN + slotIndex - 2;
}

/** "Ext-n" of an H3C's external input `trayId` (247-255): it feeds hotend 255 - trayId. */
export function rackExternalLabel(trayId: number): string {
  return `Ext-${255 - trayId + 1}`;
}
