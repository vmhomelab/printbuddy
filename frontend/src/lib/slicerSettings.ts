/**
 * Conversion between the settings panel's editing values and the string forms
 * OrcaSlicer / BambuStudio write into a process preset JSON.
 *
 * This matters more than it looks. The values we send are merged into the
 * `--load-settings` process JSON, and that JSON is parsed by the slicer CLI,
 * which validates far more strictly than the GUI: a percent option written as
 * `"20"` instead of `"20%"` is a different value, and a bare `true` where the
 * config expects `"1"` fails the parse outright. The panel therefore always
 * serialises through the schema, never by guessing from the JavaScript type.
 */

import type { ProcessOption, ProcessSchema, SettingValue } from '../types/slicerSettings';

/** Option types whose config value is a per-extruder vector. */
const VECTOR_TYPES = new Set(['coBools', 'coFloats', 'coFloatsOrPercents']);

export const isVectorOption = (option: ProcessOption): boolean => VECTOR_TYPES.has(option.type);

/**
 * Numeric bound from the schema, or `undefined` when it isn't a number at all.
 * Float literals are normalised by the generator, but a handful of bounds are
 * unresolved C++ expressions the extractor could not follow, and those must not
 * reach an input's `min`/`max`.
 */
export function numericBound(bound: number | string | undefined): number | undefined {
  if (typeof bound === 'number') return Number.isFinite(bound) ? bound : undefined;
  if (typeof bound !== 'string') return undefined;
  const n = Number.parseFloat(bound);
  return Number.isFinite(n) ? n : undefined;
}

/**
 * A unit suffix worth showing. A few entries carry an unresolved C++ expression
 * where the extractor could not follow a reference (`def_x->sidetext`); showing
 * that to a user would be worse than showing no unit at all.
 */
export function displaySidetext(option: ProcessOption): string | undefined {
  const s = option.sidetext;
  if (!s || s.includes('->') || s.includes('::')) return undefined;
  return s;
}

/**
 * What an untouched field shows.
 *
 * The picked preset's own value when we have it, else the option schema's
 * compiled-in default. The distinction is user-visible: `line_width` defaults
 * to 0 in OrcaSlicer's C++ (meaning "derive from the nozzle"), while a real
 * process preset sets something like 0.42 — showing the former for a preset
 * that sets the latter is simply wrong.
 */
export function baselineForDisplay(option: ProcessOption, presetValue?: SettingValue): string {
  const d = presetValue !== undefined ? presetValue : option.default;
  if (d === undefined) return '';
  // Per-extruder vectors render as a comma-separated list. C++ literal
  // artefacts (`0.`, `0.3f`, `100.%`) are normalised by
  // scripts/generate-slicer-schema.mjs, so nothing needs unpicking here.
  if (Array.isArray(d)) return d.map(String).join(', ');
  if (typeof d === 'boolean') return d ? '1' : '0';
  return String(d);
}

/**
 * Serialises one edited value into its process-JSON form.
 *
 * Vector options are written back as arrays because that is how the config
 * stores them; scalars become strings, which is what every Bambu process preset
 * uses even for numeric options.
 */
export function serializeSetting(option: ProcessOption, value: SettingValue): string | string[] {
  if (isVectorOption(option)) {
    const parts = Array.isArray(value) ? value.map(String) : String(value).split(',');
    return parts.map((p) => p.trim()).filter((p) => p !== '');
  }

  if (option.type === 'coBool') {
    if (typeof value === 'boolean') return value ? '1' : '0';
    return value === '1' || value === 'true' || value === 1 ? '1' : '0';
  }

  const raw = String(value).trim();

  if (option.type === 'coPercent') {
    // The config spells percents with the sign; the input edits the number.
    return raw.endsWith('%') ? raw : `${raw}%`;
  }

  return raw;
}

/** Serialises the panel's sparse override map for the slice request. */
export function serializeOverrides(values: Record<string, SettingValue>, schema: ProcessSchema): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(values)) {
    const option = schema[key];
    // A key with no schema entry cannot be serialised correctly, and sending it
    // raw risks a slice failure that is hard to trace back to this panel.
    if (!option) continue;
    out[key] = serializeSetting(option, value);
  }
  return out;
}

/**
 * True when an edited value differs from the baseline this slice would
 * otherwise use. Marks modified rows, and decides what is worth sending: an
 * override equal to what the preset already says is noise in the process JSON.
 *
 * The baseline is the preset's value when known. Comparing against the schema
 * default instead would flag every field the preset moved off the C++ default
 * as "changed by the user", and would send back values nobody typed.
 */
export function isModified(
  option: ProcessOption,
  value: SettingValue | undefined,
  presetValue?: SettingValue,
): boolean {
  if (value === undefined || value === '') return false;

  const flatten = (v: SettingValue): string => {
    const serialized = serializeSetting(option, Array.isArray(v) ? v.map(String).join(', ') : v);
    return Array.isArray(serialized) ? serialized.join(', ') : serialized;
  };

  const asString = flatten(value);
  const baseline = presetValue !== undefined ? presetValue : option.default;
  if (baseline === undefined) return asString !== '';
  return asString !== flatten(baseline as SettingValue);
}
