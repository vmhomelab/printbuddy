import { describe, it, expect } from 'vitest';

import processSchema from '../../data/slicer/process-schema.json';
import processToggles from '../../data/slicer/process-toggle-rules.json';
import processTree from '../../data/slicer/process-ui-tree.json';
import { disabledKeys, makeConfigReader } from '../../lib/slicerToggle';
import type { ProcessSchema, ProcessUiTree, SettingValue } from '../../types/slicerSettings';

const schema = processSchema as unknown as ProcessSchema;
const tree = processTree as unknown as ProcessUiTree;
const toggles = processToggles as { locals: Record<string, string>; rules: Array<{ fields: string[]; enable_if: string }> };

const disabled = (settings: Record<string, SettingValue>) => disabledKeys(settings, schema, toggles);

describe('makeConfigReader', () => {
  it('falls back to the schema default when the user has set nothing', () => {
    expect(makeConfigReader({}, schema).get('wall_loops')).toBe(2);
  });

  it('prefers a user value over the default', () => {
    expect(makeConfigReader({ wall_loops: 5 }, schema).get('wall_loops')).toBe(5);
  });

  it('reads the first entry of a per-extruder vector option', () => {
    // default_acceleration is coFloats with a default of [500].
    expect(makeConfigReader({}, schema).get('default_acceleration')).toBe(500);
  });

  it('treats an empty string as unset so a cleared input falls back to the default', () => {
    expect(makeConfigReader({ wall_loops: '' }, schema).get('wall_loops')).toBe(2);
  });
});

describe('disabledKeys', () => {
  it('disables wall-dependent options when there are no walls', () => {
    // have_perimeters = config->opt_int("wall_loops") > 0
    const off = disabled({ wall_loops: 0 });
    expect(off.has('seam_position')).toBe(true);
    expect(off.has('detect_thin_wall')).toBe(true);
  });

  it('leaves wall-dependent options enabled at the default wall count', () => {
    const off = disabled({});
    expect(off.has('seam_position')).toBe(false);
  });

  it('parses a percent value when deciding an infill condition', () => {
    // have_infill = config->option<ConfigOptionPercent>("sparse_infill_density")->value > 0
    expect(disabled({ sparse_infill_density: '0%' }).has('sparse_infill_pattern')).toBe(true);
    expect(disabled({ sparse_infill_density: '15%' }).has('sparse_infill_pattern')).toBe(false);
  });

  it('resolves a local that is defined in terms of other locals', () => {
    // have_support_material = config->opt_bool("enable_support") || have_raft,
    // and have_raft = config->opt_int("raft_layers") > 0.
    expect(disabled({ enable_support: false, raft_layers: 0 }).has('support_style')).toBe(true);
    expect(disabled({ enable_support: false, raft_layers: 3 }).has('support_style')).toBe(false);
    expect(disabled({ enable_support: true, raft_layers: 0 }).has('support_style')).toBe(false);
  });

  it('matches a C++ enumerator against the option value it serialises to', () => {
    // has_ironing = config->opt_enum<IroningType>("ironing_type") != IroningType::NoIroning
    // The enumerator is `NoIroning`; the config value is "no ironing".
    expect(disabled({ ironing_type: 'no ironing' }).has('ironing_flow')).toBe(true);
    expect(disabled({ ironing_type: 'top' }).has('ironing_flow')).toBe(false);
  });

  it('leaves a field enabled when the enumerator matches no declared value', () => {
    // support_is_organic tests `smsTreeOrganic`, which support_style spells
    // "organic" — no transliteration reaches that, so the rule must fail open
    // rather than disable organic-support fields at every setting.
    const always = disabled({});
    const flipped = disabled({ support_style: 'organic', enable_support: true });
    expect(always.has('tree_support_branch_angle_organic')).toBe(false);
    expect(flipped.has('tree_support_branch_angle_organic')).toBe(false);
  });

  it('only ever reports keys that exist in the schema', () => {
    for (const key of disabled({})) expect(schema[key]).toBeDefined();
  });

  it('decides most of the vendored rules rather than failing open on nearly all', () => {
    // Guards against a parser regression that silently degrades to "enable
    // everything" — which would still pass every assertion above. Measured at
    // 105 of 152 across these two profiles; the rest need settings these
    // probes don't touch, or reference locals we deliberately cannot resolve.
    const off = {
      wall_loops: 0, sparse_infill_density: '0%', enable_support: false, raft_layers: 0,
      spiral_mode: false, skirt_loops: 0, enable_prime_tower: false,
      top_shell_layers: 0, bottom_shell_layers: 0, infill_combination: false,
    } satisfies Record<string, SettingValue>;
    const a = disabled({});
    const b = disabled(off);
    const decided = toggles.rules.filter((rule) => rule.fields.some((f) => a.has(f) || b.has(f)));
    expect(decided.length).toBeGreaterThanOrEqual(Math.floor(toggles.rules.length * 0.6));
  });
});

describe('vendored process schema', () => {
  // The extractor reads defaults and bounds out of C++ initialisers, so float
  // literals arrive in source form — `0.`, `0.3f`, `100.%`, and `0.f` split
  // into [0, "f"]. Rendering those verbatim put a column of "0." in the Line
  // width group. scripts/generate-slicer-schema.mjs normalises them; this
  // guards a regeneration that drops that step.
  const LITERAL_ARTEFACT = /^-?[\d]*\.$|\.%$|^-?[\d.]+f$/;

  const offenders = (field: 'default' | 'min' | 'max') =>
    Object.entries(schema)
      .filter(([, opt]) => {
        const v = opt[field];
        if (Array.isArray(v)) return v.some((x) => x === 'f');
        return typeof v === 'string' && LITERAL_ARTEFACT.test(v);
      })
      .map(([key]) => `${key}.${field}`);

  it.each(['default', 'min', 'max'] as const)('carries no C++ literal artefacts in %s', (field) => {
    expect(offenders(field)).toEqual([]);
  });

  it('renders the line-width defaults as plain numbers', () => {
    // The reported symptom: every field in this group showed "0."
    for (const key of ['line_width', 'outer_wall_line_width', 'inner_wall_line_width', 'support_line_width']) {
      expect(schema[key].default).toBe('0');
    }
    expect(schema.bridge_line_width.default).toBe('100%');
  });

  it('keeps every option the UI tree references', () => {
    // A trim that drops a referenced key renders a control with no type,
    // label or default.
    for (const page of tree) {
      for (const group of page.groups) {
        for (const key of group.options) expect(schema[key]).toBeDefined();
      }
    }
  });
});
