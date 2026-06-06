import { describe, expect, it } from 'vitest';
import { getPrinterFileRuleSet, isPrintableForProvider } from '../../utils/printerFileRules';

describe('printerFileRules', () => {
  it('uses Bambu 3MF print files for Bambu printers', () => {
    const rules = getPrinterFileRuleSet('bambu');

    expect(rules.accept).toBe('.3mf,.gcode.3mf');
    expect(rules.descriptionExtensions).toBe('.3mf, .gcode.3mf');
    expect(isPrintableForProvider('plate_1.gcode.3mf', 'bambu')).toBe(true);
    expect(isPrintableForProvider('project.3mf', 'bambu')).toBe(true);
    expect(isPrintableForProvider('part.bgcode', 'bambu')).toBe(false);
  });

  it('uses BGCODE/G-code print files for PrusaLink printers', () => {
    const rules = getPrinterFileRuleSet('prusalink');

    expect(rules.accept).toBe('.bgcode,.gcode,.gco,.g');
    expect(rules.descriptionExtensions).toBe('.bgcode, .gcode, .gco, .g');
    expect(isPrintableForProvider('mk4s.bgcode', 'prusalink')).toBe(true);
    expect(isPrintableForProvider('legacy.gcode', 'prusalink')).toBe(true);
    expect(isPrintableForProvider('bambu_project.3mf', 'prusalink')).toBe(false);
  });

  it.each(['klipper', 'mainsail', 'fluidd'] as const)('uses G-code print files for %s printers', (provider) => {
    const rules = getPrinterFileRuleSet(provider);

    expect(rules.accept).toBe('.gcode,.gco,.g');
    expect(isPrintableForProvider('neptune.gcode', provider)).toBe(true);
    expect(isPrintableForProvider('neptune.bgcode', provider)).toBe(false);
    expect(isPrintableForProvider('bambu.3mf', provider)).toBe(false);
  });
});
