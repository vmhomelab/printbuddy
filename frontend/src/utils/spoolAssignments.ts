import { api } from '../api/client';

/**
 * Return the IDs of printers that have at least one spool assigned to a slot.
 *
 * Spools can be assigned in two places: the built-in inventory
 * (`/inventory/assignments`) and, when Spoolman is enabled, the Spoolman slot
 * assignments (`/spoolman/inventory/slot-assignments/all`). Both count as an
 * assigned spool. Lookup failures are treated as "no assignment" so they never
 * block a print; at worst the user sees the skippable confirmation.
 */
export async function getPrinterIdsWithSpoolAssignment(printerId?: number): Promise<Set<number>> {
  const [localAssignments, spoolmanAssignments] = await Promise.all([
    api.getAssignments(printerId).catch(() => []),
    api
      .getSpoolmanSettings()
      .then((settings) =>
        settings.spoolman_enabled === 'true' ? api.getSpoolmanSlotAssignments(printerId) : [],
      )
      .catch(() => []),
  ]);

  const printerIds = new Set<number>();
  for (const assignment of [...localAssignments, ...spoolmanAssignments]) {
    printerIds.add(assignment.printer_id);
  }
  return printerIds;
}
