import { describe, expect, it, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { PrintFarmMonitorPage } from '../../pages/PrintFarmMonitorPage';

const printers = [
  {
    id: 1,
    name: 'Demo Bambu Lab P1S',
    serial_number: 'P1S123',
    ip_address: '10.0.0.11',
    access_code: '',
    provider: 'bambu',
    api_url: null,
    auth_token: null,
    provider_options: null,
    model: 'P1S',
    location: 'Rack A-01',
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
    name: 'Demo Anycubic Kobra 2',
    serial_number: 'KOBRA2',
    ip_address: '10.0.0.12',
    access_code: '',
    provider: 'klipper',
    api_url: null,
    auth_token: null,
    provider_options: null,
    model: 'Generic FDM Printer',
    location: 'Rack C-02',
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
      name: 'Demo Bambu Lab P1S',
      connected: true,
      state: 'RUNNING',
      current_print: 'Gridfinity Calibration Tray',
      subtask_name: null,
      gcode_file: 'gridfinity.3mf',
      progress: 42,
      remaining_time: 94,
      layer_num: 84,
      total_layers: 198,
      temperatures: { nozzle: 218, bed: 60 },
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
    name: 'Demo Anycubic Kobra 2',
    connected: true,
    state: 'PAUSE',
    current_print: null,
    subtask_name: null,
    gcode_file: null,
    progress: null,
    remaining_time: null,
    layer_num: null,
    total_layers: null,
    temperatures: { nozzle: 29, bed: 28 },
    hms_errors: [],
    ams: [],
    ams_exists: false,
    vt_tray: [],
    supports_drying: false,
    awaiting_plate_clear: false,
  };
}

describe('PrintFarmMonitorPage', () => {
  beforeEach(() => {
    vi.setSystemTime(new Date('2025-05-23T10:42:00Z'));
    vi.mocked(localStorage.getItem).mockReset();
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json(printers)),
      http.get('/api/v1/printers/:id/status', ({ params }) => HttpResponse.json(statusFor(Number(params.id)))),
      http.get('/api/v1/queue/', () => HttpResponse.json([{ id: 1 }, { id: 2 }, { id: 3 }])),
      http.get('/api/v1/updates/version', () => HttpResponse.json({ version: '2.5.1', display_version: '2.5.1' })),
      http.get('/api/v1/settings/ui-preferences', () => HttpResponse.json({ print_farm_monitor_refresh_interval: 15 })),
      http.get('/api/v1/settings/', () => HttpResponse.json({ low_stock_threshold: 20 })),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ spoolman_enabled: 'false', spoolman_url: '', spoolman_sync_mode: 'read_only', spoolman_disable_weight_sync: 'false', spoolman_report_partial_usage: 'false' })),
      http.get('/api/v1/inventory/spools', () => HttpResponse.json([
        {
          id: 10,
          material: 'PLA',
          subtype: null,
          color_name: 'White',
          rgba: 'ffffff',
          extra_colors: null,
          effect_type: null,
          brand: 'RealFilament',
          label_weight: 1000,
          core_weight: 250,
          core_weight_catalog_id: null,
          weight_used: 910,
          slicer_filament: null,
          slicer_filament_name: null,
          nozzle_temp_min: null,
          nozzle_temp_max: null,
          note: null,
          added_full: true,
          last_used: null,
          encode_time: null,
          tag_uid: null,
          tray_uuid: null,
          data_origin: null,
          tag_type: null,
          archived_at: null,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
          cost_per_kg: null,
          last_scale_weight: null,
          last_weighed_at: null,
          category: 'Production shelf',
          low_stock_threshold_pct: 15,
          storage_location: 'Shelf A',
        },
      ])),
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json([
        {
          id: 1,
          spool_id: 10,
          printer_id: 1,
          printer_name: 'Demo Bambu Lab P1S',
          ams_id: -1,
          tray_id: 0,
          fingerprint_color: null,
          fingerprint_type: null,
          configured: true,
          created_at: '2024-01-01T00:00:00Z',
          spool: {
            id: 10,
            material: 'PLA',
            subtype: null,
            color_name: 'White',
            rgba: 'ffffff',
            extra_colors: null,
            effect_type: null,
            brand: 'RealFilament',
            label_weight: 1000,
            core_weight: 250,
            core_weight_catalog_id: null,
            weight_used: 910,
            slicer_filament: null,
            slicer_filament_name: null,
            nozzle_temp_min: null,
            nozzle_temp_max: null,
            note: null,
            added_full: true,
            last_used: null,
            encode_time: null,
            tag_uid: null,
            tray_uuid: null,
            data_origin: null,
            tag_type: null,
            archived_at: null,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            cost_per_kg: null,
            last_scale_weight: null,
            last_weighed_at: null,
            category: 'Production shelf',
            low_stock_threshold_pct: 15,
            storage_location: 'Shelf A',
          },
        },
      ])),
      http.get('/api/v1/maintenance/overview', () => HttpResponse.json([])),
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
          progress_percent: 50,
          archives: [],
          url: null,
          cover_image_filename: null,
        },
      ]))
    );
  });

  it('renders the TV-style print farm overview from live printer status', async () => {
    render(<PrintFarmMonitorPage />);

    expect(await screen.findByRole('heading', { name: 'Print Farm Monitor' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /back to farm command center/i })).toHaveAttribute('href', '/farm-command-center');
    expect(screen.getByText(new Date('2025-05-23T10:42:00Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }))).toBeInTheDocument();
    expect(screen.getByText(new Date('2025-05-23T10:42:00Z').toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }))).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('1 PRINTERS ACTIVE')).toBeInTheDocument());

    expect(screen.getByText(/total printers/i)).toBeInTheDocument();
    expect(screen.getByText(/printing now/i)).toBeInTheDocument();
    expect(screen.getByText(/queue size/i)).toBeInTheDocument();
    expect(screen.getByText('Gridfinity Calibration Tray')).toBeInTheDocument();
    expect(screen.getByText('42%')).toBeInTheDocument();
    expect(screen.getAllByText('PAUSED').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Demo Anycubic Kobra 2').length).toBeGreaterThan(0);
    expect(screen.getByText('ALERTS')).toBeInTheDocument();
    expect(screen.getByText('ACTIVE PROJECTS')).toBeInTheDocument();
    expect(screen.getByText('Gridfinity Organizer Set')).toBeInTheDocument();
    expect(screen.getByText('42 / 64 parts')).toBeInTheDocument();
    expect(screen.getByText('3 queued')).toBeInTheDocument();
    expect(screen.getByText('1 failed')).toBeInTheDocument();
    expect(screen.getByText('LOW FILAMENT')).toBeInTheDocument();
    expect(screen.getAllByText(/RealFilament PLA White/).length).toBeGreaterThan(0);
    expect(document.body.textContent).toContain('#FFFFFF');
    expect(document.body.textContent).not.toContain('Spool A1');
    expect(document.body.textContent).not.toContain('HEALTH OK');
    expect(screen.getByText('Recent Activity')).toBeInTheDocument();
    expect(document.body.textContent).toContain('PrintBuddy is operational');
    expect(document.body.textContent).toContain('every 15s');
    expect(document.body.textContent).toContain('Printbuddy');
    expect(document.body.textContent).toContain('v2.5.1');
  });

  it('uses fluid viewport-aware grids instead of fixed-width TV columns', async () => {
    render(<PrintFarmMonitorPage />);

    const heading = await screen.findByRole('heading', { name: 'Print Farm Monitor' });
    expect(heading.closest('main')).toHaveClass('overflow-x-hidden');
    expect(screen.getByTestId('farm-monitor-layout')).toHaveClass('min-w-0');
    expect(screen.getByTestId('farm-monitor-layout').className).toContain('min-[1280px]:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]');
    expect(screen.getByTestId('farm-monitor-layout')).toHaveClass('max-w-full');
    expect(screen.getByTestId('farm-monitor-main-column')).toContainElement(screen.getByTestId('farm-monitor-status-strip'));
    expect(screen.getByTestId('farm-monitor-main-column')).toContainElement(screen.getByTestId('farm-monitor-printer-grid'));
    expect(screen.getByTestId('farm-monitor-printer-grid')).toHaveClass('min-w-0');
    expect(screen.getByTestId('farm-monitor-printer-grid').className).toContain('grid-cols-[repeat(auto-fit,minmax(min(100%,18rem),1fr))]');
    expect(screen.getByTestId('farm-monitor-sidebar')).toHaveClass('min-w-0');
    expect(screen.getByTestId('farm-monitor-sidebar')).toHaveClass('overflow-hidden');
  });

  it('shows the assigned Spoolman spool for the active AMS slot in TV mode', async () => {
    const activeAmsStatus = {
      ...statusFor(1),
      tray_now: 2,
      ams_exists: true,
      ams: [
        {
          id: 0,
          name: 'AMS-HT',
          humidity: 20,
          temp: 42,
          is_ams_ht: false,
          serial_number: 'AMSHT123',
          sw_ver: '1.0.0',
          dry_time: 0,
          dry_status: 0,
          dry_sub_status: 0,
          dry_sf_reason: [],
          module_type: 'n3f',
          tray: [
            { id: 0, tray_type: 'PLA', tray_sub_brands: null, tray_color: 'FFFFFFFF', tray_id_name: null, tray_info_idx: null, remain: 90, k: null, cali_idx: null, tag_uid: null, tray_uuid: null, nozzle_temp_min: null, nozzle_temp_max: null, drying_temp: null, drying_time: null, state: null },
            { id: 2, tray_type: 'ABS', tray_sub_brands: null, tray_color: '111111FF', tray_id_name: null, tray_info_idx: null, remain: 75, k: null, cali_idx: null, tag_uid: null, tray_uuid: null, nozzle_temp_min: null, nozzle_temp_max: null, drying_temp: null, drying_time: null, state: null },
          ],
        },
      ],
    };
    const sunluAbs = {
      id: 42,
      material: 'ABS',
      subtype: null,
      color_name: 'Black',
      rgba: '111111',
      extra_colors: null,
      effect_type: null,
      brand: 'Sunlu',
      label_weight: 1000,
      core_weight: 250,
      core_weight_catalog_id: null,
      weight_used: 250,
      slicer_filament: null,
      slicer_filament_name: null,
      nozzle_temp_min: null,
      nozzle_temp_max: null,
      note: null,
      added_full: true,
      last_used: null,
      encode_time: null,
      tag_uid: null,
      tray_uuid: null,
      data_origin: null,
      tag_type: null,
      archived_at: null,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
      cost_per_kg: null,
      last_scale_weight: null,
      last_weighed_at: null,
      category: 'Production shelf',
      low_stock_threshold_pct: 15,
      storage_location: 'Shelf A',
    };

    server.use(
      http.get('/api/v1/printers/:id/status', ({ params }) => HttpResponse.json(Number(params.id) === 1 ? activeAmsStatus : statusFor(Number(params.id)))),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ spoolman_enabled: 'true', spoolman_url: 'http://spoolman.local', spoolman_sync_mode: 'read_only', spoolman_disable_weight_sync: 'false', spoolman_report_partial_usage: 'false' })),
      http.get('/api/v1/spoolman/inventory/spools', () => HttpResponse.json([sunluAbs])),
      http.get('/api/v1/spoolman/inventory/slot-assignments/all', () => HttpResponse.json([
        { printer_id: 1, printer_name: 'Demo Bambu Lab P1S', ams_id: 0, tray_id: 2, spoolman_spool_id: 42, ams_label: 'AMS-HT' },
      ])),
    );

    render(<PrintFarmMonitorPage />);

    await waitFor(() => expect(screen.getByText('1 PRINTERS ACTIVE')).toBeInTheDocument());
    expect(screen.getByText('Sunlu ABS Black')).toBeInTheDocument();
    expect(screen.getByText(/AMS 0 tray 2/)).toBeInTheDocument();
    expect(screen.getByText(/75%/)).toBeInTheDocument();
  });

  it('does not mark idle printers as printing when stale completed job metadata remains', async () => {
    server.use(
      http.get('/api/v1/printers/:id/status', ({ params }) => {
        const id = Number(params.id);
        if (id === 1) {
          return HttpResponse.json({
            id,
            name: 'Demo Bambu Lab P1S',
            connected: true,
            state: 'PRINTING',
            current_print: 'Finished Gridfinity Plate',
            subtask_name: null,
            gcode_file: 'finished-gridfinity-plate.gcode.3mf',
            progress: 100,
            remaining_time: 0,
            layer_num: 1228,
            total_layers: 1228,
            temperatures: { nozzle: 33, bed: 32 },
            hms_errors: [],
            ams: [],
            ams_exists: false,
            vt_tray: [],
            supports_drying: false,
            awaiting_plate_clear: false,
          });
        }
        return HttpResponse.json(statusFor(id));
      }),
    );

    render(<PrintFarmMonitorPage />);

    await screen.findAllByText('Demo Bambu Lab P1S');
    await waitFor(() => expect(screen.getByText('0 PRINTERS ACTIVE')).toBeInTheDocument());
    expect(screen.getAllByText('IDLE').length).toBeGreaterThan(0);
    expect(screen.queryByText('Finished Gridfinity Plate')).not.toBeInTheDocument();
    expect(screen.queryByText('100%')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('1228 / 1228 layers');
  });

  it('does not render the current time as ETA when a running printer reports zero remaining time', async () => {
    server.use(
      http.get('/api/v1/printers/:id/status', ({ params }) => {
        const id = Number(params.id);
        if (id === 1) {
          return HttpResponse.json({
            ...statusFor(id),
            remaining_time: 0,
          });
        }
        return HttpResponse.json(statusFor(id));
      }),
    );

    render(<PrintFarmMonitorPage />);

    await waitFor(() => expect(screen.getByText('1 PRINTERS ACTIVE')).toBeInTheDocument());
    expect(document.body.textContent).not.toContain('10:42 AM');
    expect(document.body.textContent).toContain('ETA —');
  });

  it('follows the selected PrintBuddy light theme', async () => {
    vi.mocked(localStorage.getItem).mockImplementation((key: string) => (
      key === 'theme-mode' ? 'light' : null
    ));

    render(<PrintFarmMonitorPage />);

    const heading = await screen.findByRole('heading', { name: 'Print Farm Monitor' });
    const monitor = heading.closest('main');
    expect(monitor).toHaveAttribute('data-monitor-theme', 'light');
    expect(monitor).toHaveClass('bg-bambu-dark');
    expect(screen.getByAltText('Printbuddy')).toHaveAttribute('src', '/img/printbuddy_logo_light.png');
  });
});
