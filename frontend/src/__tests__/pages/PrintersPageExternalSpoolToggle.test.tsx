/**
 * Hiding the external spool from the printer card (#1782, reporter @Arn0uDz).
 *
 * The toggle lives in the filament section header next to the AMS Backup
 * badge. It is offered only when an AMS is present: on a printer that feeds
 * from the external spool alone, the external spool IS the filament section,
 * so hiding it would leave an empty row and no way to see the loaded filament.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { PrintersPage } from '../../pages/PrintersPage';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

const STORE_KEY = 'printerHiddenExternalSpools';

const mockPrinter = {
  id: 1,
  name: 'X1C',
  ip_address: '192.168.1.100',
  serial_number: '01P00A000000001',
  access_code: '12345678',
  model: 'X1C',
  enabled: true,
  nozzle_diameter: 0.4,
  nozzle_type: 'stainless_steel',
  location: 'Workshop',
  auto_archive: true,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const baseTray = {
  tray_color: 'FF0000FF',
  tray_type: 'PLA',
  tray_sub_brands: 'PLA Basic',
  tray_id_name: 'A00-R0',
  tray_info_idx: 'GFA00',
  remain: 80,
  k: 0.02,
  cali_idx: null,
  tag_uid: null,
  tray_uuid: null,
  nozzle_temp_min: 190,
  nozzle_temp_max: 230,
  drying_temp: null,
  drying_time: null,
  state: 3,
};

const amsUnit = {
  id: 0,
  humidity: 30,
  temp: 33,
  is_ams_ht: false,
  serial_number: 'AMS00',
  sw_ver: '03.00.21.29',
  dry_time: 0,
  dry_status: 0,
  dry_sub_status: 0,
  dry_sf_reason: [],
  module_type: 'n3f',
  tray: [0, 1, 2, 3].map((id) => ({ id, ...baseTray })),
};

function makeStatus({ withAms }: { withAms: boolean }) {
  return {
    connected: true,
    state: 'IDLE',
    progress: 0,
    layer_num: 0,
    total_layers: 0,
    temperatures: { nozzle: 25, bed: 25, chamber: 25 },
    remaining_time: 0,
    filename: null,
    wifi_signal: -29,
    speed_level: 2,
    supports_drying: true,
    drying_screen_only: false,
    ams: withAms ? [amsUnit] : [],
    vt_tray: [{ id: 254, ...baseTray, tray_type: 'PETG', tray_sub_brands: 'PETG HF' }],
  };
}

const WITH_AMS = makeStatus({ withAms: true });
const WITHOUT_AMS = makeStatus({ withAms: false });

const HIDE_TITLE = 'Hide external spool';
const SHOW_TITLE = 'Show external spool';

/** The external spool's own card is labelled with `printers.external`. */
function externalSpoolCards() {
  return screen.queryAllByText('External');
}

let store: Record<string, string>;

describe('PrintersPage — hide the external spool (#1782)', () => {
  beforeEach(() => {
    store = {};
    vi.mocked(localStorage.getItem).mockImplementation((key: string) => store[key] ?? null);
    vi.mocked(localStorage.setItem).mockImplementation((key: string, value: string) => {
      store[key] = String(value);
    });
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([mockPrinter])),
      http.get('/api/v1/queue/', () => HttpResponse.json([])),
    );
  });

  afterEach(() => {
    vi.mocked(localStorage.getItem).mockReset();
    vi.mocked(localStorage.setItem).mockReset();
  });

  it('hides the external spool when the toggle is clicked, and brings it back', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/v1/printers/:id/status', () => HttpResponse.json(WITH_AMS)));

    render(<PrintersPage />);

    const toggle = await screen.findByTitle(HIDE_TITLE);
    expect(externalSpoolCards().length).toBeGreaterThan(0);

    await user.click(toggle);
    await waitFor(() => expect(externalSpoolCards()).toHaveLength(0));

    // The toggle itself stays put — it is the only way back.
    const restore = await screen.findByTitle(SHOW_TITLE);
    await user.click(restore);
    await waitFor(() => expect(externalSpoolCards().length).toBeGreaterThan(0));
  });

  it('persists the choice per printer', async () => {
    const user = userEvent.setup();
    server.use(http.get('/api/v1/printers/:id/status', () => HttpResponse.json(WITH_AMS)));

    render(<PrintersPage />);
    await user.click(await screen.findByTitle(HIDE_TITLE));

    // Keyed by printer id, so a second printer's card is untouched.
    await waitFor(() => {
      expect(JSON.parse(store[STORE_KEY])).toEqual({ '1': true });
    });
  });

  it('starts hidden when the stored preference says so', async () => {
    store[STORE_KEY] = JSON.stringify({ '1': true });
    server.use(http.get('/api/v1/printers/:id/status', () => HttpResponse.json(WITH_AMS)));

    render(<PrintersPage />);

    await screen.findByTitle(SHOW_TITLE);
    expect(externalSpoolCards()).toHaveLength(0);
  });

  it('does not offer the toggle on a printer with no AMS', async () => {
    server.use(http.get('/api/v1/printers/:id/status', () => HttpResponse.json(WITHOUT_AMS)));

    render(<PrintersPage />);

    // The external spool is the whole filament section here, so it must stay.
    await waitFor(() => expect(externalSpoolCards().length).toBeGreaterThan(0));
    expect(screen.queryByTitle(HIDE_TITLE)).not.toBeInTheDocument();
    expect(screen.queryByTitle(SHOW_TITLE)).not.toBeInTheDocument();
  });

  it('ignores a stored preference once the printer has no AMS left', async () => {
    // The AMS was unplugged after the user hid the external spool. Honouring
    // the stored flag would blank the filament row with no control to undo it.
    store[STORE_KEY] = JSON.stringify({ '1': true });
    server.use(http.get('/api/v1/printers/:id/status', () => HttpResponse.json(WITHOUT_AMS)));

    render(<PrintersPage />);

    await waitFor(() => expect(externalSpoolCards().length).toBeGreaterThan(0));
    expect(screen.queryByTitle(SHOW_TITLE)).not.toBeInTheDocument();
  });
});
