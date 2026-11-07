/**
 * Tests for getPrinterImage — model → printer card image resolver.
 *
 * X2D support (#988): both the display name "X2D" and the internal SSDP
 * code "N6" must resolve to /img/printers/x2d.png so the Printers page
 * and PrinterInfoModal show the correct artwork instead of falling back
 * to default.png.
 */

import { describe, it, expect } from 'vitest';
import { getPrinterDisplayImage, getPrinterImage, isGcodeCompatible, filterCompatibleQueueItems } from '../../utils/printer';
import type { PrintQueueItem } from '../../api/client';

describe('getPrinterImage', () => {
  it('prefers a printer custom image over the model artwork', () => {
    expect(getPrinterDisplayImage({ id: 42, model: 'P1S', custom_image_filename: 'printer_42_new.png' }))
      .toBe('/api/v1/printers/42/image?v=printer_42_new.png');
  });

  it('falls back to model artwork when a printer has no custom image', () => {
    expect(getPrinterDisplayImage({ id: 42, model: 'P1S', custom_image_filename: null }))
      .toBe('/img/printers/p1s.png');
  });

  describe('X2D (#988)', () => {
    it('resolves display name "X2D" to x2d.png', () => {
      expect(getPrinterImage('X2D')).toBe('/img/printers/x2d.png');
    });

    it('resolves case-insensitive variants', () => {
      expect(getPrinterImage('x2d')).toBe('/img/printers/x2d.png');
      expect(getPrinterImage(' X2D ')).toBe('/img/printers/x2d.png');
    });

    it('resolves the internal SSDP code "N6" to x2d.png', () => {
      expect(getPrinterImage('N6')).toBe('/img/printers/x2d.png');
    });

    it('does not match X2D on unrelated model strings', () => {
      // Regression guard: a hypothetical future "X2" model must not
      // silently pick up x2d.png until it's explicitly mapped.
      expect(getPrinterImage('X2E')).toBe('/img/printers/default.png');
    });
  });

  describe('A2L (#1684)', () => {
    it('resolves display name and SSDP code to a2l.png', () => {
      expect(getPrinterImage('A2L')).toBe('/img/printers/a2l.png');
      expect(getPrinterImage('N9')).toBe('/img/printers/a2l.png');
      expect(getPrinterImage('Bambu Lab A2L')).toBe('/img/printers/a2l.png');
    });

    it('resolves case-insensitive variants', () => {
      expect(getPrinterImage('a2l')).toBe('/img/printers/a2l.png');
      expect(getPrinterImage(' A2L ')).toBe('/img/printers/a2l.png');
    });

    it('does not match A2L on unrelated A-series strings', () => {
      // Regression guard: a hypothetical future "A2M" or similar must not
      // silently pick up a2l.png until it's explicitly mapped, and "A1" /
      // "A1 Mini" must still resolve to their own artwork.
      expect(getPrinterImage('A2M')).toBe('/img/printers/default.png');
      expect(getPrinterImage('A1')).toBe('/img/printers/a1.png');
      expect(getPrinterImage('A1 Mini')).toBe('/img/printers/a1mini.png');
    });
  });

  describe('regression: existing families unchanged', () => {
    it('X1C → x1c.png', () => {
      expect(getPrinterImage('X1C')).toBe('/img/printers/x1c.png');
    });

    it('X1E → x1e.png', () => {
      expect(getPrinterImage('X1E')).toBe('/img/printers/x1e.png');
    });

    it('H2D → h2d.png', () => {
      expect(getPrinterImage('H2D')).toBe('/img/printers/h2d.png');
    });

    it('H2D Pro → h2dpro.png', () => {
      expect(getPrinterImage('H2D Pro')).toBe('/img/printers/h2dpro.png');
    });

    it('P2S → p1s.png (shared with P1S)', () => {
      // Pre-existing behaviour: P2S currently reuses the P1S artwork. Not
      // changed by the X2D diff; asserted to catch accidental regressions.
      expect(getPrinterImage('P2S')).toBe('/img/printers/p1s.png');
    });

    it('A1 Mini → a1mini.png (not a1.png)', () => {
      // The "a1mini" branch must run before the generic "a1" branch —
      // the X2D branch was inserted above both and must not break order.
      expect(getPrinterImage('A1 Mini')).toBe('/img/printers/a1mini.png');
    });

    it('A1 F → a1f.png (not a1.png)', () => {
      expect(getPrinterImage('A1 F')).toBe('/img/printers/a1f.png');
      expect(getPrinterImage('A1-F')).toBe('/img/printers/a1f.png');
    });

    it('O1 family resolves to its specific artwork', () => {
      expect(getPrinterImage('O1C')).toBe('/img/printers/o1c.png');
      expect(getPrinterImage('O1E')).toBe('/img/printers/o1e.png');
      expect(getPrinterImage('O1S')).toBe('/img/printers/o1s.png');
    });

    it('non-Bambu models with bundled artwork resolve to their images', () => {
      const expected: Array<[string, string]> = [
        ['Elegoo Neptune 3', 'elegoo-neptune-3.png'],
        ['Elegoo Neptune 3 Pro', 'elegoo-neptune-3-pro.png'],
        ['Elegoo Neptune 3 Plus', 'elegoo-neptune-3-plus.png'],
        ['Elegoo Neptune 3 Max', 'elegoo-neptune-3-max.png'],
        ['Elegoo Neptune 4', 'elegoo-neptune-4.png'],
        ['Elegoo Neptune 4 Pro', 'elegoo-neptune-4-pro.png'],
        ['Elegoo Neptune 4 Plus', 'elegoo-neptune-4-plus.png'],
        ['Elegoo Neptune 4 Max', 'elegoo-neptune-4-max.png'],
        ['Elegoo Centauri Carbon', 'elegoo-centauri-carbon.png'],
        ['Creality K1', 'creality-k1.png'],
        ['Creality K1C', 'creality-k1c.png'],
        ['Creality K2 Plus', 'creality-k2-plus.png'],
        ['Snapmaker U1', 'snapmaker-u1.png'],
        ['Prusa CORE One', 'prusa-core-one.png'],
        ['Prusa MK4S', 'prusa-mk4s.png'],
        ['Prusa MK4', 'prusa-mk4.png'],
        ['Prusa MK3.9S', 'prusa-mk3.9S.png'],
        ['Prusa MK3.9', 'prusa-mk3.9.png'],
        ['Prusa MK3.5S', 'prusa-mk3.5S.png'],
        ['Prusa MK3.5', 'prusa-mk3.5.png'],
        ['Prusa XL', 'prusa-xl.png'],
        ['Prusa MINI+', 'prusa-mini+.png'],
        ['Prusa MK3S+', 'prusa-mk3s+.png'],
      ];

      for (const [model, filename] of expected) {
        expect(getPrinterImage(model), model).toBe(`/img/printers/${filename}`);
      }
    });

    it('keeps adjacent non-Bambu models distinct', () => {
      expect(getPrinterImage('Elegoo Neptune 4')).toBe('/img/printers/elegoo-neptune-4.png');
      expect(getPrinterImage('Elegoo Neptune 4 Pro')).toBe('/img/printers/elegoo-neptune-4-pro.png');
      expect(getPrinterImage('Elegoo Centauri Carbon')).toBe('/img/printers/elegoo-centauri-carbon.png');
      expect(getPrinterImage('Elegoo Centauri')).toBe('/img/printers/default.png');
      expect(getPrinterImage('Prusa MK4')).toBe('/img/printers/prusa-mk4.png');
      expect(getPrinterImage('Prusa MK4S')).toBe('/img/printers/prusa-mk4s.png');
      expect(getPrinterImage('Creality K1')).toBe('/img/printers/creality-k1.png');
      expect(getPrinterImage('Creality K1C')).toBe('/img/printers/creality-k1c.png');
      expect(getPrinterImage('Creality K2 Plus')).toBe('/img/printers/creality-k2-plus.png');
      expect(getPrinterImage('Creality K10')).toBe('/img/printers/default.png');
      expect(getPrinterImage('Snapmaker U1')).toBe('/img/printers/snapmaker-u1.png');
      expect(getPrinterImage('Snapmaker U2')).toBe('/img/printers/default.png');
    });

    it('uses the Home Assistant ingress base for static printer images', () => {
      window.history.replaceState({}, '', '/api/hassio_ingress/abc123/printers');
      expect(getPrinterImage('P1S')).toBe('/api/hassio_ingress/abc123/img/printers/p1s.png');
      window.history.replaceState({}, '', '/');
    });

    it('uses generic-printer.png for models from the Generic group', () => {
      const genericModels = ['Klipper', 'PrusaLink', 'Generic Klipper Printer', 'Generic FDM Printer'];

      for (const model of genericModels) {
        expect(getPrinterImage(model), model).toBe('/img/printers/generic-printer.png');
      }
    });

    it('null / undefined → default.png', () => {
      expect(getPrinterImage(null)).toBe('/img/printers/default.png');
      expect(getPrinterImage(undefined)).toBe('/img/printers/default.png');
    });

    it('unknown model → default.png', () => {
      expect(getPrinterImage('SomeFuturePrinter')).toBe(
        '/img/printers/default.png',
      );
    });
  });
});

// Mirrors backend/tests/unit/test_scheduler_model_mismatch.py — the frontend
// table must stay in sync with backend GCODE_COMPAT_FAMILIES (#2578).
describe('isGcodeCompatible', () => {
  it('accepts same model', () => {
    expect(isGcodeCompatible('X1C', 'X1C')).toBe(true);
    expect(isGcodeCompatible('H2D', 'H2D')).toBe(true);
  });

  it('accepts the X1/P1 interchange family', () => {
    expect(isGcodeCompatible('X1C', 'P1S')).toBe(true);
    expect(isGcodeCompatible('X1C', 'P1P')).toBe(true);
    expect(isGcodeCompatible('P1S', 'X1E')).toBe(true);
    expect(isGcodeCompatible('X1', 'P1P')).toBe(true);
  });

  it('rejects cross-family targets', () => {
    // The reporter's case: X1C-sliced G-code targeted at an H2D (#2578)
    expect(isGcodeCompatible('X1C', 'H2D')).toBe(false);
    expect(isGcodeCompatible('P1S', 'H2D')).toBe(false);
    expect(isGcodeCompatible('X1C', 'A1')).toBe(false);
    expect(isGcodeCompatible('A1', 'A1 Mini')).toBe(false);
    expect(isGcodeCompatible('H2D', 'H2S')).toBe(false);
    expect(isGcodeCompatible('X1C', 'P2S')).toBe(false);
  });

  it('is fail-safe on unknown metadata', () => {
    expect(isGcodeCompatible(null, 'H2D')).toBe(true);
    expect(isGcodeCompatible('X1C', null)).toBe(true);
    expect(isGcodeCompatible(undefined, undefined)).toBe(true);
    expect(isGcodeCompatible('', 'H2D')).toBe(true);
  });

  it('normalizes case, spaces and dashes', () => {
    expect(isGcodeCompatible('x1c', 'X1C')).toBe(true);
    expect(isGcodeCompatible('A1 Mini', 'A1-MINI')).toBe(true);
    expect(isGcodeCompatible('H2D Pro', 'H2DPRO')).toBe(true);
  });
});

describe('filterCompatibleQueueItems — force-color PLA variant (#2650)', () => {
  const makeItem = (
    overrides: Array<{ slot_id: number; type: string; color: string; tray_info_idx?: string; force_color_match?: boolean }>,
  ): PrintQueueItem => ({ id: 1, filament_overrides: overrides } as unknown as PrintQueueItem);

  // A job sliced for White PLA Matte (GFA01).
  const matteJob = makeItem([
    { slot_id: 1, type: 'PLA', color: '#FFFFFF', tray_info_idx: 'GFA01', force_color_match: true },
  ]);
  const loadedTypes = new Set(['PLA']);
  const loaded = new Set(['PLA:ffffff']);

  it('rejects a printer loaded only with other white PLA variants (Basic/Silk)', () => {
    const variants = new Set(['PLA:ffffff:GFA00', 'PLA:ffffff:GFA06']);
    expect(filterCompatibleQueueItems([matteJob], loadedTypes, loaded, variants)).toHaveLength(0);
  });

  it('accepts a printer loaded with the matching variant (Matte GFA01)', () => {
    const variants = new Set(['PLA:ffffff:GFA00', 'PLA:ffffff:GFA01']);
    expect(filterCompatibleQueueItems([matteJob], loadedTypes, loaded, variants)).toHaveLength(1);
  });

  it('accepts a same-colour spool that reports no tray_info_idx (custom/third-party)', () => {
    const variants = new Set(['PLA:ffffff:']);
    expect(filterCompatibleQueueItems([matteJob], loadedTypes, loaded, variants)).toHaveLength(1);
  });

  it('falls back to type+colour when no variant data is supplied', () => {
    // loadedVariants omitted → the hint is never stricter than the data it has.
    expect(filterCompatibleQueueItems([matteJob], loadedTypes, loaded)).toHaveLength(1);
  });

  it('an override without a tray_info_idx keeps the old type+colour behaviour', () => {
    const noIdxJob = makeItem([{ slot_id: 1, type: 'PLA', color: '#FFFFFF', force_color_match: true }]);
    const variants = new Set(['PLA:ffffff:GFA06']);
    expect(filterCompatibleQueueItems([noIdxJob], loadedTypes, loaded, variants)).toHaveLength(1);
  });
});

describe('filterCompatibleQueueItems — printer-targeted jobs (#3133)', () => {
  // A job moved from "Any P2S" to one P2S keeps its override. The printer is
  // already chosen, so a colour it has not loaded must not hide the job from
  // that printer's card — the scheduler maps the trays at dispatch.
  const boneWhite = [{ slot_id: 1, type: 'PLA', color: '#F5F5DC', force_color_match: false }];
  const loadedTypes = new Set(['PLA']);
  const loadedBrown = new Set(['PLA:8b4513']);

  it('keeps a specific-printer job whose override colour is not loaded', () => {
    const item = { id: 1, printer_id: 3, filament_overrides: boneWhite } as unknown as PrintQueueItem;
    expect(filterCompatibleQueueItems([item], loadedTypes, loadedBrown)).toHaveLength(1);
  });

  it('still filters the same job while it targets any printer of a model', () => {
    const item = { id: 1, printer_id: null, target_model: 'P2S', filament_overrides: boneWhite } as unknown as PrintQueueItem;
    expect(filterCompatibleQueueItems([item], loadedTypes, loadedBrown)).toHaveLength(0);
  });
});
