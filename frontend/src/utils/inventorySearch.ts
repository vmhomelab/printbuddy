import type { InventorySpool } from '../api/client';

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

  const searchableValues = [
    String(spool.id),
    spool.material,
    spool.brand,
    spool.color_name,
    spool.subtype,
    spool.note,
    spool.slicer_filament_name,
    spool.storage_location,
    spool.data_origin,
    ...(spool.data_origin === 'openfilamentdatabase'
      ? ['ofdb', 'open filament database', 'openfilamentdatabase']
      : []),
  ]
    .filter((value): value is string => Boolean(value))
    .map((value) => value.toLowerCase());

  return terms.every((term) => searchableValues.some((value) => value.includes(term)));
}

/** Filter a spool list by a free-text search query. */
export function filterSpoolsByQuery(spools: InventorySpool[], query: string): InventorySpool[] {
  if (!query) return spools;
  return spools.filter((spool) => spoolMatchesQuery(spool, query));
}
