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
      state: 'PRINTING',
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
    state: 'PAUSED',
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
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json(printers)),
      http.get('/api/v1/printers/:id/status', ({ params }) => HttpResponse.json(statusFor(Number(params.id)))),
      http.get('/api/v1/queue/', () => HttpResponse.json([{ id: 1 }, { id: 2 }, { id: 3 }])),
      http.get('/api/v1/updates/version', () => HttpResponse.json({ version: '2.5.1', display_version: '2.5.1' }))
    );
  });

  it('renders the TV-style print farm overview from live printer status', async () => {
    render(<PrintFarmMonitorPage />);

    expect(await screen.findByRole('heading', { name: 'Print Farm Monitor' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('1 PRINTERS ACTIVE')).toBeInTheDocument());

    expect(screen.getByText(/total printers/i)).toBeInTheDocument();
    expect(screen.getByText(/printing now/i)).toBeInTheDocument();
    expect(screen.getByText(/queue size/i)).toBeInTheDocument();
    expect(screen.getByText('Gridfinity Calibration Tray')).toBeInTheDocument();
    expect(screen.getByText('42%')).toBeInTheDocument();
    expect(screen.getAllByText('PAUSED').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Demo Anycubic Kobra 2').length).toBeGreaterThan(0);
    expect(screen.getByText('ALERTS')).toBeInTheDocument();
    expect(screen.getByText('Recent Activity')).toBeInTheDocument();
    expect(document.body.textContent).toContain('Printbuddy');
    expect(document.body.textContent).toContain('v2.5.1');
  });
});
