// Regenerates the vendored OrcaSlicer process-settings metadata under
// src/data/slicer/ from the `three-slicer` npm package.
//
// Why vendored and not a runtime dependency: we need three of the package's
// four data files, trimmed to the *process* tab only, and none of its engine,
// viewer or React code.
// Pulling `three-slicer` as a dependency would drag in an 8 MB WASM kernel and
// a `three@^0.160` peer pin that conflicts with our three@^0.181.
//
// Usage:  node scripts/generate-slicer-schema.mjs <path-to-three-slicer-package>
//
// The upstream data is AGPL-3.0-or-later, extracted from OrcaSlicer's C++
// sources — same licence as Printbuddy, so vendoring is clean. Re-run this when
// bumping to a newer three-slicer release and commit the regenerated output.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

const src = process.argv[2];
if (!src) {
  console.error('usage: node scripts/generate-slicer-schema.mjs <path-to-three-slicer-package>');
  process.exit(1);
}

const OUT_DIR = resolve(import.meta.dirname, '..', 'src', 'data', 'slicer');

const readJson = (p) => JSON.parse(readFileSync(join(src, p), 'utf8'));

const schema = readJson('data/config-schema.json');
const uiTree = readJson('data/ui-tree.json');
const toggles = readJson('data/toggle-rules.json');

// --- 1. UI tree, process tab only -----------------------------------------
// TabPrint::build is the process/print preset — the one whose JSON our slice
// route patches. Filament and printer presets are separate objects on the
// sidecar and out of scope for this panel.
const pages = uiTree['TabPrint::build'];
if (!Array.isArray(pages)) throw new Error('ui-tree.json has no TabPrint::build array');

// Tab.cpp references that PrintConfig.cpp no longer defines, collected while
// walking the tree so the run can report them.
const dropped = [];

// Drop the C++ source line numbers: useful for the extractor, noise for us.
const trimmedPages = pages.map((page) => ({
  page: page.page,
  icon: page.icon,
  groups: (page.groups ?? []).map((g) => ({
    group: g.group,
    options: (g.options ?? []).filter((key) => {
      if (!schema[key]) {
        // A handful of Tab.cpp references point at options that no longer
        // exist in PrintConfig.cpp. Silently dropping them keeps the panel
        // from rendering a control with no type, label or default.
        dropped.push(key);
        return false;
      }
      return true;
    }),
  })).filter((g) => g.options.length > 0),
})).filter((p) => p.groups.length > 0);

// --- 2. Schema, trimmed to the options the tree actually references --------
const referenced = new Set(trimmedPages.flatMap((p) => p.groups.flatMap((g) => g.options)));

// Toggle rules reference options for their *conditions* too (e.g. wall_loops
// gates have_perimeters). Those must survive the trim or the evaluator reads a
// default of `undefined` and fails open on a rule it could have decided.
const CONDITION_KEYS = [
  'wall_loops', 'sparse_infill_density', 'top_shell_layers', 'bottom_shell_layers',
  'spiral_mode', 'skirt_loops', 'enable_support', 'raft_layers', 'enable_prime_tower',
  'support_interface_top_layers', 'support_interface_bottom_layers', 'sparse_infill_pattern',
  'support_type', 'support_style', 'wall_generator', 'timelapse_type', 'infill_combination',
  'detect_thin_wall', 'ironing_type', 'default_acceleration', 'adaptive_layer_height',
];
for (const k of CONDITION_KEYS) if (schema[k]) referenced.add(k);

// Only the fields the panel renders or the evaluator reads. This is what keeps
// the vendored payload proportionate: the upstream schema is 384 KB across 907
// options, most of it source-location bookkeeping we have no use for.
const KEEP = ['type', 'mode', 'label', 'tooltip', 'sidetext', 'min', 'max', 'enum_values', 'enum_labels', 'default'];

// The extractor reads defaults and bounds straight out of C++ initialisers, so
// float literals arrive in source form: `0.` stays "0.", `0.3f` stays "0.3f",
// `100.%` stays "100.%", and `0.f` even splits into [0, "f"]. Rendering those
// verbatim put a column of "0." in the Line width group. They are literal
// artefacts, not values, so they are cleaned here — once, in the data — rather
// than worked around in every place that displays a default.
function normaliseLiteral(value) {
  if (Array.isArray(value)) {
    // `0.f` split across two entries; the stray "f" is not a value.
    const cleaned = value.filter((v) => v !== 'f').map(normaliseLiteral);
    return cleaned.length > 0 ? cleaned : [0];
  }
  if (typeof value !== 'string') return value;

  let s = value.trim();
  s = s.replace(/^(-?[\d.]+)f$/, '$1');   // 0.3f -> 0.3,  0.f -> 0.
  s = s.replace(/^(-?[\d.]*)\.%$/, '$1%'); // 100.% -> 100%
  s = s.replace(/^(-?[\d.]*)\.$/, '$1');   // 0. -> 0
  // A literal that was nothing but a dot carried no digits to keep.
  if (s === '' || s === '-') return value;
  return s;
}

const trimmedSchema = {};
for (const key of [...referenced].sort()) {
  const opt = schema[key];
  const out = {};
  for (const f of KEEP) {
    if (opt[f] === undefined) continue;
    out[f] = f === 'default' || f === 'min' || f === 'max' ? normaliseLiteral(opt[f]) : opt[f];
  }
  trimmedSchema[key] = out;
}

// --- 3. Toggle rules, FFF print options only ------------------------------
// The other rule groups drive the filament and printer tabs, which this panel
// does not render.
const fff = toggles['toggle_print_fff_options'] ?? {};
const trimmedToggles = {
  locals: fff.locals ?? {},
  rules: (fff.rules ?? [])
    .filter((r) => r.enable_if && Array.isArray(r.fields))
    // A rule whose fields are all outside our trimmed set can never change
    // anything the panel shows.
    .map((r) => ({ fields: r.fields.filter((f) => referenced.has(f)), enable_if: r.enable_if }))
    .filter((r) => r.fields.length > 0),
};

mkdirSync(OUT_DIR, { recursive: true });
const write = (name, data) => {
  const path = join(OUT_DIR, name);
  writeFileSync(path, JSON.stringify(data, null, 0) + '\n');
  return `${name}: ${(readFileSync(path).length / 1024).toFixed(1)} KB`;
};

console.log(write('process-ui-tree.json', trimmedPages));
console.log(write('process-schema.json', trimmedSchema));
console.log(write('process-toggle-rules.json', trimmedToggles));
console.log(`options: ${Object.keys(trimmedSchema).length}, pages: ${trimmedPages.length}, rules: ${trimmedToggles.rules.length}`);
if (dropped.length) console.log(`dropped (no schema entry): ${dropped.join(', ')}`);
