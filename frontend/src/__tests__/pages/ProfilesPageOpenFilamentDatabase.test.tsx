import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { ProfilesPage } from '../../pages/ProfilesPage';

const settingsResponse = {
  auto_archive: true,
  save_thumbnails: true,
  capture_finish_photo: true,
  default_filament_cost: 25.0,
  currency: 'USD',
  energy_cost_per_kwh: 0.15,
  energy_tracking_mode: 'total',
  check_updates: true,
  check_printer_firmware: true,
  include_beta_updates: false,
  language: 'en',
  notification_language: 'en',
  ams_humidity_good: 40,
  ams_humidity_fair: 60,
  ams_temp_good: 28,
  ams_temp_fair: 35,
  ams_history_retention_days: 30,
  queue_drying_enabled: false,
  queue_drying_block: false,
  ambient_drying_enabled: false,
  drying_presets: '',
  gcode_snippets: '',
  local_backup_enabled: false,
  local_backup_schedule: 'daily',
  local_backup_time: '03:00',
  local_backup_retention: 5,
  local_backup_path: '',
  per_printer_mapping_expanded: false,
  date_format: 'system',
  time_format: '24h',
  disable_filament_warnings: false,
  prefer_lowest_filament: false,
  open_filament_database_enabled: false,
  default_printer_id: null,
  dark_style: 'vibrant',
  dark_background: 'cool',
  dark_accent: 'teal',
  light_style: 'classic',
  light_background: 'neutral',
  light_accent: 'teal',
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
  panda_breath_enabled: false,
  panda_breath_topic_prefix: 'panda_breath',
  panda_breath_printer_assignments: '{}',
  external_url: '',
  ha_enabled: false,
  ha_url: '',
  ha_token: '',
  ha_url_from_env: false,
  ha_token_from_env: false,
  ha_env_managed: false,
  library_archive_mode: 'ask',
  library_disk_warning_gb: 5,
  camera_view_mode: 'window',
  preferred_slicer: 'orcaslicer',
  use_slicer_api: false,
  orcaslicer_api_url: '',
  bambu_studio_api_url: '',
  prometheus_enabled: false,
  prometheus_token: '',
  bed_cooled_threshold: 35,
  low_stock_threshold: 20,
  user_notifications_enabled: true,
  default_bed_levelling: true,
  default_flow_cali: false,
  default_vibration_cali: true,
  default_layer_inspect: false,
  default_timelapse: false,
  stagger_group_size: 2,
  stagger_interval_minutes: 5,
  require_plate_clear: false,
  queue_shortest_first: false,
  default_sidebar_order: '',
  ldap_enabled: false,
  ldap_server_url: '',
  ldap_bind_dn: '',
  ldap_bind_password: '',
  ldap_search_base: '',
  ldap_user_filter: '',
  ldap_security: 'none',
  ldap_group_mapping: '{}',
  ldap_auto_provision: false,
  ldap_default_group: '',
  obico_enabled: false,
  obico_ml_url: '',
  obico_sensitivity: 'medium',
  obico_action: 'notify',
  obico_poll_interval: 30,
  obico_enabled_printers: '[]',
  forecast_global_lead_time_days: 7,
};

describe('ProfilesPage Open Filament Database settings', () => {
  it('renders the OFDB tab and persists the enable toggle', async () => {
    let putBody: Record<string, unknown> | null = null;

    server.use(
      http.get('/api/v1/settings/', () => HttpResponse.json(settingsResponse)),
      http.put('/api/v1/settings/', async ({ request }) => {
        putBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...settingsResponse, ...putBody });
      }),
    );

    render(<ProfilesPage />);

    await userEvent.click(await screen.findByRole('button', { name: /open filament database api/i }));

    expect(screen.getByRole('heading', { name: 'Open Filament Database API' })).toBeInTheDocument();
    expect(
      screen.getByText(/Choose whether PrintBuddy should search for filament data via Open Filament Database/i),
    ).toBeInTheDocument();

    const checkbox = await screen.findByRole('checkbox', { name: /search spools via open filament database/i });
    expect(checkbox).not.toBeChecked();

    await userEvent.click(checkbox);

    await waitFor(() => {
      expect(putBody).toEqual({ open_filament_database_enabled: true });
    });
  });
});
