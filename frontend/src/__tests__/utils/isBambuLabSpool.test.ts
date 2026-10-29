/**
 * Tests for isBambuLabSpool helper.
 *
 * Requires 32-hex tray_uuid or 16-hex tag_uid so synthetic Snapmaker slot
 * IDs are not treated as firmware-owned Bambu RFID.
 */

import { describe, it, expect } from 'vitest';

import { getTrayFilamentSpoolId, isBambuLabSpool } from '../../utils/amsHelpers';

describe('isBambuLabSpool', () => {
  it('returns false for null', () => {
    expect(isBambuLabSpool(null)).toBe(false);
  });

  it('returns false for undefined', () => {
    expect(isBambuLabSpool(undefined)).toBe(false);
  });

  it('returns false for an empty object', () => {
    expect(isBambuLabSpool({})).toBe(false);
  });

  it('returns true for a valid 32-hex non-zero tray_uuid', () => {
    expect(
      isBambuLabSpool({ tray_uuid: '11223344556677880011223344556677' }),
    ).toBe(true);
  });

  it('returns false for the zero-string 32-char tray_uuid', () => {
    expect(
      isBambuLabSpool({ tray_uuid: '00000000000000000000000000000000' }),
    ).toBe(false);
  });

  it('returns true for a valid 16-hex non-zero tag_uid', () => {
    expect(isBambuLabSpool({ tag_uid: 'AABBCC1122334400' })).toBe(true);
  });

  it('returns false for the zero-string 16-char tag_uid', () => {
    expect(isBambuLabSpool({ tag_uid: '0000000000000000' })).toBe(false);
  });

  it('returns false when both fields are explicitly null', () => {
    expect(isBambuLabSpool({ tray_uuid: null, tag_uid: null })).toBe(false);
  });

  it('returns true when only tag_uid is set and tray_uuid is null', () => {
    expect(
      isBambuLabSpool({ tray_uuid: null, tag_uid: 'AABBCC1122334400' }),
    ).toBe(true);
  });

  it('returns true when only tray_uuid is set and tag_uid is null', () => {
    expect(
      isBambuLabSpool({
        tray_uuid: '11223344556677880011223344556677',
        tag_uid: null,
      }),
    ).toBe(true);
  });

  it('returns false for Snapmaker synthetic tray_uuid values', () => {
    expect(isBambuLabSpool({ tray_uuid: 'snapmaker-u1-e0', tag_uid: '' })).toBe(false);
  });
});

describe('getTrayFilamentSpoolId', () => {
  it('returns positive spool ids from SpoolLink telemetry', () => {
    expect(getTrayFilamentSpoolId({ filament_spool_id: 25 })).toBe(25);
  });

  it('ignores missing, zero, and negative ids', () => {
    expect(getTrayFilamentSpoolId(undefined)).toBeUndefined();
    expect(getTrayFilamentSpoolId({ filament_spool_id: 0 })).toBeUndefined();
    expect(getTrayFilamentSpoolId({ filament_spool_id: -1 })).toBeUndefined();
  });
});
