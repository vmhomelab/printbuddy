/**
 * Tests for the optional "arrange AMS by nozzle side" toggle on PrintersPage (#56).
 *
 * Dual-nozzle printers (H2D) show the left-nozzle AMS on the left of their own
 * display. The toggle mirrors that layout; it is off by default, persisted per
 * printer, and not offered on single-nozzle printers.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { PrintersPage } from '../../pages/PrintersPage';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

const TOGGLE_OFF_LABEL = 'Arrange AMS by nozzle side, like the printer display';
const TOGGLE_ON_LABEL = 'AMS arranged by nozzle side, like the printer display (click for default order)';

const mockPrinter = {
  id: 7,
  name: 'H2D',
  ip_address: '192.168.1.107',
  serial_number: '0948AD000000007',
  access_code: '12345678',
  model: 'H2D',
  nozzle_count: 2,
  enabled: true,
  nozzle_diameter: 0.4,
  nozzle_type: 'hardened_steel',
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
  state: 11,
};

const makeAms = (id: number) => ({
  id,
  humidity: 30,
  temp: 25,
  is_ams_ht: false,
  serial_number: `AMS0${id}`,
  sw_ver: '1.0.0',
  dry_time: 0,
  dry_status: 0,
  dry_sub_status: 0,
  dry_sf_reason: [],
  module_type: 'ams',
  tray: [0, 1, 2, 3].map((slot) => ({ id: slot, ...baseTray })),
});

const mockStatus = {
  connected: true,
  state: 'IDLE',
  progress: 0,
  layer_num: 0,
  total_layers: 0,
  temperatures: { nozzle: 25, nozzle_2: 25, bed: 25, chamber: 25 },
  remaining_time: 0,
  filename: null,
  wifi_signal: -50,
  speed_level: 2,
  vt_tray: [],
  // AMS-A feeds the right nozzle (extruder 0), AMS-B the left nozzle (extruder 1).
  ams: [makeAms(0), makeAms(1)],
  ams_extruder_map: { '0': 0, '1': 1 },
};

/** AMS labels in DOM (= visual) order. */
const amsLabelOrder = () =>
  Array.from(document.querySelectorAll('span, div'))
    .filter((el) => el.children.length === 0 && /^AMS-[AB]$/.test(el.textContent ?? ''))
    .map((el) => el.textContent);

describe('PrintersPage - arrange AMS by nozzle side (#56)', () => {
  beforeEach(() => {
    vi.mocked(localStorage.getItem).mockReset();
    vi.mocked(localStorage.setItem).mockReset();
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([mockPrinter])),
      http.get('/api/v1/queue/', () => HttpResponse.json([])),
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(mockStatus)),
    );
  });

  it('keeps the default AMS order until the toggle is used', async () => {
    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getByLabelText(TOGGLE_OFF_LABEL)).toBeInTheDocument();
    });
    expect(amsLabelOrder()).toEqual(['AMS-A', 'AMS-B']);
  });

  it('puts the left-nozzle AMS first when enabled and remembers the choice', async () => {
    const user = userEvent.setup();
    render(<PrintersPage />);

    await user.click(await screen.findByLabelText(TOGGLE_OFF_LABEL));

    await waitFor(() => {
      expect(screen.getByLabelText(TOGGLE_ON_LABEL)).toHaveAttribute('aria-pressed', 'true');
    });
    expect(amsLabelOrder()).toEqual(['AMS-B', 'AMS-A']);
    expect(localStorage.setItem).toHaveBeenCalledWith('amsOrderByNozzleSide_7', 'true');
  });

  it('restores a saved preference per printer', async () => {
    vi.mocked(localStorage.getItem).mockImplementation((key: string) =>
      key === 'amsOrderByNozzleSide_7' ? 'true' : null,
    );
    render(<PrintersPage />);

    expect(await screen.findByLabelText(TOGGLE_ON_LABEL)).toHaveAttribute('aria-pressed', 'true');
    expect(amsLabelOrder()).toEqual(['AMS-B', 'AMS-A']);
  });

  it('does not offer the toggle on single-nozzle printers', async () => {
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([{ ...mockPrinter, model: 'X1C', nozzle_count: 1 }])),
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json({
        ...mockStatus,
        temperatures: { nozzle: 25, bed: 25, chamber: 25 },
        ams_extruder_map: {},
      })),
    );
    render(<PrintersPage />);

    await waitFor(() => {
      expect(amsLabelOrder()).toEqual(['AMS-A', 'AMS-B']);
    });
    expect(screen.queryByLabelText(TOGGLE_OFF_LABEL)).not.toBeInTheDocument();
  });
});
