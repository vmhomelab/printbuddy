import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { getPrinterIdsWithSpoolAssignment } from '../../utils/spoolAssignments';

const spoolmanSlot = (printerId: number) => ({
  printer_id: printerId,
  printer_name: null,
  ams_id: 0,
  tray_id: 0,
  spoolman_spool_id: 33,
  ams_label: null,
});

describe('getPrinterIdsWithSpoolAssignment', () => {
  it('combines inventory and Spoolman slot assignments', async () => {
    server.use(
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json([{ id: 1, printer_id: 1, ams_id: 0, tray_id: 0 }])),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ spoolman_enabled: 'true' })),
      http.get('/api/v1/spoolman/inventory/slot-assignments/all', () => HttpResponse.json([spoolmanSlot(2)])),
    );

    const ids = await getPrinterIdsWithSpoolAssignment();

    expect([...ids].sort()).toEqual([1, 2]);
  });

  it('ignores Spoolman slot assignments when Spoolman is disabled', async () => {
    server.use(
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json([])),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ spoolman_enabled: 'false' })),
      http.get('/api/v1/spoolman/inventory/slot-assignments/all', () => HttpResponse.json([spoolmanSlot(2)])),
    );

    const ids = await getPrinterIdsWithSpoolAssignment();

    expect(ids.size).toBe(0);
  });

  it('treats lookup failures as no assignment instead of throwing', async () => {
    server.use(
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );

    const ids = await getPrinterIdsWithSpoolAssignment();

    expect(ids.size).toBe(0);
  });
});
