import { describe, expect, it, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { FarmCommandCenterPage } from '../../pages/FarmCommandCenterPage';

const printers = [
  {
    id: 1,
    name: 'PRA-01',
    serial_number: 'PRA01',
    ip_address: '10.0.0.11',
    access_code: '',
    provider: 'bambu',
    api_url: null,
    auth_token: null,
    provider_options: null,
    model: 'P1S',
    location: 'Production Row A',
    nozzle_count: 1,
    is_active: true,
    auto_archive: true,
    external_camera_url: null,
    external_camera_type: null,
    external_camera_enabled: false,
    external_camera_snapshot_url: null,
    camera_rotation: 0,
    plate_detection_enabled: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 2,
    name: 'PRB-04',
    serial_number: 'PRB04',
    ip_address: '10.0.0.12',
    access_code: '',
    provider: 'klipper',
    api_url: null,
    auth_token: null,
    provider_options: null,
    model: 'Generic FDM Printer',
    location: 'Engineering Row B',
    nozzle_count: 1,
    is_active: true,
    auto_archive: true,
    external_camera_url: null,
    external_camera_type: null,
    external_camera_enabled: false,
    external_camera_snapshot_url: null,
    camera_rotation: 0,
    plate_detection_enabled: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
];

function statusFor(id: number) {
  if (id === 1) {
    return {
      id,
      name: 'PRA-01',
      connected: true,
      state: 'PRINTING',
      current_print: 'Gridfinity Tray',
      subtask_name: null,
      gcode_file: 'gridfinity.3mf',
      progress: 68,
      remaining_time: 120,
      layer_num: 10,
      total_layers: 100,
      temperatures: { nozzle: 220, bed: 60 },
      hms_errors: [],
      ams: [],
      ams_exists: false,
      vt_tray: [],
      supports_drying: false,
      awaiting_plate_clear: false,
    };
  }
  return {
    id,
    name: 'PRB-04',
    connected: true,
    state: 'PAUSED',
    current_print: null,
    subtask_name: null,
    gcode_file: null,
    progress: null,
    remaining_time: null,
    layer_num: null,
    total_layers: null,
    temperatures: { nozzle: 28, bed: 27 },
    hms_errors: [],
    ams: [],
    ams_exists: false,
    vt_tray: [],
    supports_drying: false,
    awaiting_plate_clear: false,
  };
}

describe('FarmCommandCenterPage', () => {
  let printerFleetGroups: Array<{ id: number; name: string; color: null; sort_order: number; printer_ids: number[]; created_at: string; updated_at: string }>;

  beforeEach(() => {
    vi.setSystemTime(new Date('2026-07-02T16:42:17Z'));
    vi.mocked(localStorage.getItem).mockReset();
    vi.mocked(localStorage.setItem).mockReset();
    printerFleetGroups = [];
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json(printers)),
      http.get('/api/v1/printer-fleet-groups/', () => HttpResponse.json(printerFleetGroups)),
      http.post('/api/v1/printer-fleet-groups/', async ({ request }) => {
        const body = await request.json() as { name: string; printer_ids: number[]; sort_order?: number };
        const group = {
          id: 101,
          name: body.name,
          color: null,
          sort_order: body.sort_order ?? 0,
          printer_ids: body.printer_ids,
          created_at: '2026-07-02T16:42:17Z',
          updated_at: '2026-07-02T16:42:17Z',
        };
        printerFleetGroups = [group];
        return HttpResponse.json(group);
      }),
      http.get('/api/v1/printers/:id/status', ({ params }) => HttpResponse.json(statusFor(Number(params.id)))),
      http.get('/api/v1/queue/', () => HttpResponse.json([
        { id: 1, status: 'completed', completed_at: '2026-07-02T12:00:00Z', project_id: 42, library_file_id: null, library_file_name: null, archive_name: 'completed-gridfinity.gcode.3mf', printer_name: 'PRA-01' },
        { id: 2, status: 'pending', completed_at: null, project_id: 42, library_file_id: 41, library_file_name: 'gridfinity-bin-plate-03.gcode.3mf', archive_name: null, printer_name: null },
      ])),
      http.get('/api/v1/settings/', () => HttpResponse.json({ low_stock_threshold: 20 })),
      http.get('/api/v1/inventory/spools', () => HttpResponse.json([
        {
          id: 10,
          material: 'PLA',
          subtype: null,
          color_name: 'White',
          rgba: 'ffffff',
          brand: 'RealFilament',
          label_weight: 1000,
          weight_used: 910,
          archived_at: null,
          low_stock_threshold_pct: 15,
        },
      ])),
      http.get('/api/v1/maintenance/overview', () => HttpResponse.json([
        {
          printer_id: 2,
          printer_name: 'PRB-04',
          maintenance_items: [
            { enabled: true, is_due: true, is_warning: false, interval_type: 'hours', hours_until_due: 0, days_until_due: null, maintenance_type_name: 'Nozzle check' },
          ],
        },
      ])),
      http.get('/api/v1/projects/', () => HttpResponse.json([
        {
          id: 42,
          name: 'Gridfinity Organizer Set',
          description: 'Modular storage system for workstations',
          color: '#3b82f6',
          status: 'active',
          target_count: 8,
          target_parts_count: 64,
          budget: null,
          created_at: '2024-01-01T00:00:00Z',
          archive_count: 4,
          total_items: 48,
          completed_count: 42,
          failed_count: 1,
          queue_count: 3,
          progress_percent: 68,
          archives: [],
          url: null,
          cover_image_filename: null,
        },
      ]))
    );
  });

  it('renders the command center and links TV Mode to the kiosk monitor', async () => {
    render(<FarmCommandCenterPage />);

    expect(await screen.findByRole('heading', { name: 'Farm Command Center' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('Production Row A').length).toBeGreaterThan(0));

    expect(screen.getByText('Fleet Status')).toBeInTheDocument();
    expect(screen.getByText('PRA-01')).toBeInTheDocument();
    expect(screen.getByText('PRB-04')).toBeInTheDocument();
    expect(screen.getAllByText('Gridfinity Organizer Set').length).toBeGreaterThan(0);
    expect(screen.getByText('42 / 64 Parts')).toBeInTheDocument();
    expect(screen.getByText('3 queued')).toBeInTheDocument();
    expect(screen.getByText('1 failed')).toBeInTheDocument();
    expect(screen.getByText('Filament Stock')).toBeInTheDocument();
    expect(screen.getByText('Maintenance')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /tv mode/i })).toHaveAttribute('href', '/farm-monitor');
    expect(screen.getByRole('button', { name: /create group/i })).toBeInTheDocument();
    expect(screen.getAllByRole('link').some((link) => link.getAttribute('href') === '/inventory')).toBe(true);
    expect(screen.getAllByRole('link').some((link) => link.getAttribute('href') === '/maintenance')).toBe(true);
    expect(screen.getAllByRole('link').some((link) => link.getAttribute('href') === '/projects/42')).toBe(true);
    expect(screen.getByRole('heading', { name: 'Dispatch Suggestions' })).toBeInTheDocument();
    expect(screen.getByText('Review 1 active project with 3 queued jobs and 1 failed job.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /review gridfinity organizer set dispatch/i })).toHaveAttribute('href', '/projects/42');
    expect(screen.getByText('Printing now')).toBeInTheDocument();
    expect(screen.getByText('PRA-01 - Gridfinity Tray - 68%')).toBeInTheDocument();
    expect(screen.getByText('Queued')).toBeInTheDocument();
    expect(screen.getByText('gridfinity-bin-plate-03.gcode.3mf')).toBeInTheDocument();
  });

  it('opens an alerts pop-up from the alerts stat card', async () => {
    const user = userEvent.setup();
    render(<FarmCommandCenterPage />);

    await screen.findByRole('heading', { name: 'Farm Command Center' });
    await user.click(screen.getByRole('button', { name: /alerts/i }));

    const dialog = await screen.findByRole('dialog', { name: /command center alerts/i });
    expect(within(dialog).getAllByText('PRB-04').length).toBeGreaterThan(0);
    expect(within(dialog).getByText(/Paused/)).toBeInTheDocument();
    expect(within(dialog).getByText(/White PLA/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Nozzle check/)).toBeInTheDocument();
  });

  it('creates printer groups and assigns printers inside the command center', async () => {
    const user = userEvent.setup();
    render(<FarmCommandCenterPage />);

    await screen.findByRole('heading', { name: 'Farm Command Center' });
    await user.click(screen.getByRole('button', { name: /create group/i }));

    const dialog = await screen.findByRole('dialog', { name: /printer groups/i });
    await user.type(within(dialog).getByLabelText(/group name/i), 'Prototype Lab');
    await user.click(within(dialog).getByRole('checkbox', { name: /PRA-01/i }));
    await user.click(within(dialog).getByRole('button', { name: /save group/i }));

    await waitFor(() => expect(screen.getAllByText('Prototype Lab').length).toBeGreaterThan(0));
    expect(localStorage.setItem).not.toHaveBeenCalledWith('printbuddy.commandCenterPrinterGroups', expect.any(String));
    expect(printerFleetGroups[0]).toMatchObject({ name: 'Prototype Lab', printer_ids: [1] });
  });
});
