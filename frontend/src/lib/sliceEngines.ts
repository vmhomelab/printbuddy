/**
 * Registry of the available slicing engines.
 *
 * "Engine" here means *where slicing runs*, which is a separate axis from the
 * `preferred_slicer` setting (that one only selects which slicer binary the
 * server-side sidecar drives). Keeping them apart avoids having to represent
 * combinations that don't exist — there is no browser build of BambuStudio, so
 * a single dropdown mixing the two would offer choices that cannot work.
 *
 * Today exactly one engine is registered. The registry exists so that adding a
 * browser/WASM engine is a matter of pushing a second entry: the settings card
 * and the slice modal both derive their UI from `availableEngines()`, so a
 * second engine makes the pickers appear without either of them changing.
 *
 * Deliberately *not* shipping a disabled "In browser" option in the meantime.
 * An option a user can see but never pick reads as a broken feature, and there
 * is nothing behind it yet: the WASM engine returns raw G-code, while dispatch
 * needs a `.gcode.3mf` container, so browser slicing cannot reach a printer
 * until that packaging exists.
 */

export type SliceEngineId = 'sidecar' | 'browser';

export interface SliceEngine {
  id: SliceEngineId;
  /** i18n key for the human-readable name. */
  labelKey: string;
  /** i18n key for the one-line explanation shown under the picker. */
  descriptionKey: string;
  /**
   * False while an engine is defined but not yet usable. Unavailable engines
   * are never offered; they exist here so the surrounding code can be written
   * against the full set rather than special-cased later.
   */
  available: boolean;
}

const ENGINES: SliceEngine[] = [
  {
    id: 'sidecar',
    labelKey: 'settings.sliceEngineSidecar',
    descriptionKey: 'settings.sliceEngineSidecarHint',
    available: true,
  },
  {
    id: 'browser',
    labelKey: 'settings.sliceEngineBrowser',
    descriptionKey: 'settings.sliceEngineBrowserHint',
    available: false,
  },
];

export const DEFAULT_SLICE_ENGINE: SliceEngineId = 'sidecar';

/** Engines a user can actually pick right now. */
export function availableEngines(): SliceEngine[] {
  return ENGINES.filter((e) => e.available);
}

/** True when there is a real choice to present. */
export function hasEngineChoice(): boolean {
  return availableEngines().length > 1;
}

/**
 * Resolves a stored or per-job engine id to one that can actually run.
 *
 * A setting can outlive the engine it names — an install that had browser
 * slicing enabled and then loaded a build without it must still be able to
 * slice, so an unavailable id falls back rather than failing.
 */
export function resolveEngine(id: string | null | undefined): SliceEngineId {
  const match = availableEngines().find((e) => e.id === id);
  return match?.id ?? DEFAULT_SLICE_ENGINE;
}
