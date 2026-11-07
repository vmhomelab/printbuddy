import type { InventorySpool } from '../api/client';
import { resolveSpoolColorName } from './colors';

/**
 * The spool ID a "#<number>" query asks for, or null for any other query.
 *
 * A hash-prefixed number is an explicit spool ID lookup. Plain numeric
 * searches stay backwards-compatible ("3" can still match #3, #13, #30, ...),
 * while "#3" selects only the physical spool whose label says #3.
 */
export function exactSpoolIdQuery(query: string): number | null {
  const match = query.trim().match(/^#(\d+)$/);
  return match ? Number(match[1]) : null;
}

/**
 * Return true when spool matches the search query across all searchable text fields.
 * Case-insensitive. Empty or whitespace-only query always returns true.
 * Multi-word queries match when every term appears in at least one searchable field.
 */
export function spoolMatchesQuery(spool: InventorySpool, query: string): boolean {
  const terms = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);

  if (terms.length === 0) return true;

  const exactId = exactSpoolIdQuery(query);
  if (exactId !== null) return spool.id === exactId;

  const searchableValues = [
    String(spool.id),
    spool.material,
    spool.brand,
    // Both the stored name and the displayed one. They differ often: a Bambu
    // tag may carry no colour name or an internal code, and Spoolman has no
    // such field, so what the list shows is usually resolved from the swatch's
    // hex. Searching only the stored value means typing what you can plainly
    // read finds nothing (#3090).
    spool.color_name,
    resolveSpoolColorName(spool.color_name, spool.rgba, spool.color_name_is_synthesized),
    spool.subtype,
    spool.note,
    spool.slicer_filament_name,
    spool.storage_location,
    spool.material_number,
    ...(spool.suppliers ?? []).flatMap((link) => [link.supplier_name, link.supplier_article_number]),
    spool.data_origin,
    ...(spool.data_origin === 'openfilamentdatabase'
      ? ['ofdb', 'open filament database', 'openfilamentdatabase']
      : []),
  ]
    .filter((value): value is string => Boolean(value))
    .map((value) => value.toLowerCase());

  return terms.every((term) => {
    // A hash-prefixed number is an explicit spool ID lookup. Keep plain numeric
    // searches backwards-compatible ("3" can still match #3, #13, #30, ...),
    // while "#3" selects only the physical spool whose label says #3 (#2978).
    const exactIdQuery = term.match(/^#(\d+)$/);
    if (exactIdQuery) {
      return spool.id === Number(exactIdQuery[1]);
    }
    return searchableValues.some((value) => value.includes(term));
  });
}

/** Filter a spool list by a free-text search query. */
export function filterSpoolsByQuery(spools: InventorySpool[], query: string): InventorySpool[] {
  if (!query) return spools;
  return spools.filter((spool) => spoolMatchesQuery(spool, query));
}
