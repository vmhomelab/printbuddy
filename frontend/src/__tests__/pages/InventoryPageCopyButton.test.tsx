/**
 * Tests for the copy-spool button in InventoryPage.
 *
 * Three callsites — table-row, card, and grouped-view inner row — each wire
 * onCopy from the page-level setFormModal({ spool, mode: 'copy' }) state.
 * These tests cover the two visually distinct components (SpoolTableRow and
 * SpoolCard). The grouped-view path is SpoolTableGroup which renders inner
 * SpoolTableRow rows with onCopy={onCopy ? () => onCopy(spool) : undefined} —
 * a one-line forward of the same callback the table-row test already
 * exercises end-to-end.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { render } from '../utils';
import InventoryPageRouter from '../../pages/InventoryPage';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

const baseSpool = {
  subtype: null,
  brand: 'eSun',
  color_name: 'Blue',
  rgba: '0000FFFF',
  extra_colors: null,
  effect_type: null,
  label_weight: 1000,
  core_weight: 250,
  core_weight_catalog_id: null,
  slicer_filament: null,
  slicer_filament_name: null,
  nozzle_temp_min: null,
  nozzle_temp_max: null,
  note: null,
  added_full: null,
  last_used: null,
  encode_time: null,
  tag_uid: null,
  tray_uuid: null,
  data_origin: null,
  tag_type: null,
  archived_at: null,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  k_profiles: [] as never[],
  cost_per_kg: null,
  last_scale_weight: null,
  last_weighed_at: null,
  storage_location: null,
  category: null,
  low_stock_threshold_pct: null,
  spoolman_id: null,
  spoolman_filament_id: null,
};

const MOCK_SPOOL = {
  ...baseSpool,
  id: 5,
  material: 'PETG',
  weight_used: 400,
};

const MOCK_SETTINGS = {
  auto_archive: false,
  save_thumbnails: false,
  capture_finish_photo: false,
  default_filament_cost: 25.0,
  currency: 'USD',
  energy_cost_per_kwh: 0.15,
  energy_tracking_mode: 'total',
  spoolman_enabled: false,
  spoolman_url: '',
  spoolman_sync_mode: 'auto',
  spoolman_disable_weight_sync: false,
  spoolman_report_partial_usage: true,
  check_updates: false,
  check_printer_firmware: false,
  include_beta_updates: false,
  language: 'en',
  notification_language: 'en',
  bed_cooled_threshold: 35,
  ams_humidity_good: 40,
  ams_humidity_fair: 60,
  ams_temp_good: 28,
  ams_temp_fair: 35,
  ams_history_retention_days: 30,
  per_printer_mapping_expanded: false,
  date_format: 'system',
  time_format: 'system',
  default_printer_id: null,
  virtual_printer_enabled: false,
  virtual_printer_access_code: '',
  virtual_printer_mode: 'immediate',
  dark_style: 'classic',
  dark_background: 'neutral',
  dark_accent: 'green',
  light_style: 'classic',
  light_background: 'neutral',
  light_accent: 'green',
  ftp_retry_enabled: true,
  ftp_retry_count: 3,
  ftp_retry_delay: 2,
  ftp_timeout: 30,
  mqtt_enabled: false,
  mqtt_broker: '',
  mqtt_port: 1883,
  mqtt_username: '',
  mqtt_password: '',
  mqtt_topic_prefix: 'printbuddy',
  mqtt_use_tls: false,
  external_url: '',
  ha_enabled: false,
  ha_url: '',
  ha_token: '',
  ha_url_from_env: false,
  ha_token_from_env: false,
  ha_env_managed: false,
  library_archive_mode: 'ask',
  library_disk_warning_gb: 5.0,
  camera_view_mode: 'window',
  preferred_slicer: 'bambu_studio',
  prometheus_enabled: false,
  prometheus_token: '',
  low_stock_threshold: 20.0,
};

function setupHandlers(spools: unknown[] = [MOCK_SPOOL]) {
  server.use(
    http.get('/api/v1/settings/', () => HttpResponse.json(MOCK_SETTINGS)),
    http.get('/api/v1/settings/spoolman', () =>
      HttpResponse.json({
        spoolman_enabled: 'false',
        spoolman_url: '',
        spoolman_sync_mode: 'auto',
        spoolman_disable_weight_sync: 'false',
        spoolman_report_partial_usage: 'true',
      })
    ),
    http.get('/api/v1/inventory/spools', () => HttpResponse.json(spools)),
    http.get('/api/v1/inventory/assignments', () => HttpResponse.json([])),
    http.get('/api/v1/inventory/catalog', () => HttpResponse.json([])),
    // SpoolFormModal kicks off these fetches the moment it opens. Without
    // handlers MSW would passthrough to the real network and ECONNREFUSED;
    // those promises then resolve after the test environment is torn down,
    // surfacing as an unhandled rejection in the modal's setState finally.
    http.get('/api/v1/cloud/status', () =>
      HttpResponse.json({ is_authenticated: false })
    ),
    http.get('/api/v1/cloud/local-presets', () =>
      HttpResponse.json({ filament: [], printer: [], process: [] })
    ),
    http.get('/api/v1/local-presets/', () =>
      HttpResponse.json({ filament: [], printer: [], process: [] })
    ),
    http.get('/api/v1/cloud/builtin-filaments', () => HttpResponse.json([])),
    http.get('/api/v1/inventory/color-catalog', () => HttpResponse.json([])),
    http.get('/api/v1/inventory/colors', () => HttpResponse.json([])),
    http.get('/api/v1/inventory/spool-catalog', () => HttpResponse.json([])),
    http.get('/api/v1/printers/', () => HttpResponse.json([])),
  );
}

describe('InventoryPage — copy button', () => {
  beforeEach(() => {
    setupHandlers();
  });

  it('opens SpoolFormModal in "Copy Spool" mode when the copy button in the table row is clicked', async () => {
    render(<InventoryPageRouter />);

    // Wait for the spool list to render
    await waitFor(() => {
      expect(screen.getAllByText('PETG').length).toBeGreaterThan(0);
    });

    // Find the "Copy Spool" button (title attribute) in the table row
    const copyButtons = await screen.findAllByTitle('Copy Spool');
    expect(copyButtons.length).toBeGreaterThan(0);

    // Click the first copy button (table view is default)
    fireEvent.click(copyButtons[0]);

    // The modal should open with the "Copy Spool" heading
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Copy Spool' })).toBeInTheDocument();
    });
  });

  it('opens SpoolFormModal in "Copy Spool" mode when the copy button in the cards view is clicked', async () => {
    render(<InventoryPageRouter />);

    await waitFor(() => {
      expect(screen.getAllByText('PETG').length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole('button', { name: /^Cards$/ }));

    const copyButtons = await screen.findAllByTitle('Copy Spool');
    expect(copyButtons.length).toBeGreaterThan(0);
    fireEvent.click(copyButtons[0]);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Copy Spool' })).toBeInTheDocument();
    });
  });

  it('assigns a spool to a printer from the inventory table', async () => {
    const assignmentSpy = vi.fn();
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([
        {
          id: 7,
          name: 'Prusa CORE One',
          serial_number: 'PRUSA-CORE-ONE',
          ip_address: '10.17.10.50',
          access_code: '',
          provider: 'prusalink',
          api_url: null,
          auth_token: null,
          provider_options: null,
          model: 'Prusa CORE One',
          location: null,
          nozzle_count: 1,
          is_active: true,
          auto_archive: true,
          external_camera_url: null,
          external_camera_type: null,
          external_camera_enabled: false,
          external_camera_snapshot_url: null,
          camera_rotation: 0,
          plate_detection_enabled: false,
          created_at: '2025-01-01T00:00:00Z',
          updated_at: '2025-01-01T00:00:00Z',
        },
      ])),
      http.post('/api/v1/inventory/assignments', async ({ request }) => {
        const body = await request.json();
        assignmentSpy(body);
        return HttpResponse.json({
          id: 123,
          spool_id: 5,
          printer_id: 7,
          printer_name: 'Prusa CORE One',
          ams_id: -1,
          tray_id: 0,
          ams_label: null,
          fingerprint_color: null,
          fingerprint_type: null,
          configured: true,
          created_at: '2025-01-01T00:00:00Z',
        });
      })
    );

    render(<InventoryPageRouter />);

    await waitFor(() => {
      expect(screen.getAllByText('PETG').length).toBeGreaterThan(0);
    });

    const assignButtons = await screen.findAllByTitle('Assign to printer');
    fireEvent.click(assignButtons[0]);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Assign to printer' })).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Printer'), { target: { value: '7' } });
    const submitAssignButton = screen
      .getAllByRole('button', { name: 'Assign to printer' })
      .find((button) => button.textContent?.trim() === 'Assign to printer');
    expect(submitAssignButton).toBeTruthy();
    fireEvent.click(submitAssignButton!);

    await waitFor(() => {
      expect(assignmentSpy).toHaveBeenCalledWith({ spool_id: 5, printer_id: 7, ams_id: -1, tray_id: 0 });
    });
  });

});
