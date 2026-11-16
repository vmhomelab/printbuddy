import { describe, expect, it } from 'vitest';
import {
  ams3hSlotOf,
  externalSlotIndex,
  externalTrayId,
  isAms3hUnit,
  isH3cModel,
  rackExternalLabel,
} from '../../utils/trayIds';
import { formatSlotLabel, getGlobalTrayId } from '../../utils/amsHelpers';
import { mapModelCode } from '../../utils/printerModels';
import { getMaintenanceWikiUrl } from '../../utils/maintenanceWikiUrls';

describe('H3C tray numbering', () => {
  it('numbers the AMS 3H as 28 + slot', () => {
    expect(getGlobalTrayId(32, 0, false)).toBe(28);
    expect(getGlobalTrayId(32, 8, false)).toBe(36);
    expect(ams3hSlotOf(31)).toBe(3);
    expect(ams3hSlotOf(37)).toBeNull();
  });

  it('keeps the numbering of every other unit', () => {
    expect(getGlobalTrayId(0, 3, false)).toBe(3);
    expect(getGlobalTrayId(1, 2, false)).toBe(6);
    expect(getGlobalTrayId(128, 0, false)).toBe(128);
    expect(getGlobalTrayId(255, 0, true)).toBe(254);
    expect(getGlobalTrayId(255, 1, true)).toBe(255);
  });

  it('maps the per-hotend external inputs', () => {
    expect(externalTrayId(2)).toBe(247);
    expect(externalTrayId(8)).toBe(253);
    expect(externalSlotIndex(247)).toBe(2);
    expect(externalSlotIndex(254)).toBe(0);
    expect(externalSlotIndex(255)).toBe(1);
    expect(getGlobalTrayId(255, 4, true)).toBe(249);
    expect(rackExternalLabel(255)).toBe('Ext-1');
    expect(rackExternalLabel(247)).toBe('Ext-9');
  });

  it('labels AMS 3H slots and inputs', () => {
    expect(formatSlotLabel(32, 4, false, false)).toBe('3H-5');
    expect(formatSlotLabel(255, 2, false, true)).toBe('Ext-9');
    expect(formatSlotLabel(255, 0, false, true)).toBe('Ext');
    expect(formatSlotLabel(1, 0, false, false)).toBe('B1');
  });

  it('recognises the AMS 3H unit and the H3C model', () => {
    expect(isAms3hUnit({ id: 32, ams_type: 6, tray: [] })).toBe(true);
    expect(isAms3hUnit({ id: 32, tray: new Array(9).fill({}) })).toBe(true);
    expect(isAms3hUnit({ id: 0, ams_type: 1, tray: new Array(4).fill({}) })).toBe(false);
    expect(isH3cModel('H3C')).toBe(true);
    expect(isH3cModel('N10')).toBe(true);
    expect(isH3cModel('H2C')).toBe(false);
    expect(mapModelCode('N10')).toBe('H3C');
  });

  it('links the H3C belt-tension guide', () => {
    expect(getMaintenanceWikiUrl('Check Belt Tension', 'H3C')).toBe(
      'https://wiki.bambulab.com/en/h3c/maintenance/belt_tension',
    );
  });
});
