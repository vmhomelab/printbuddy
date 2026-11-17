/**
 * Tests for the AMS slot load / unload buttons on PrintersPage (#891).
 *
 * The printer-card refactor in #1661 replaced the kebab "Slot options"
 * button with a hover card (FilamentHoverCard) whose actions render on
 * hover. Tests now `fireEvent.mouseEnter` on the slot trigger
 * (`data-testid="filament-slot"`) and wait for the portaled card to
 * appear in document.body before clicking Load / Unload.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { PrintersPage } from '../../pages/PrintersPage';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

const mockPrinter = {
  id: 1,
  name: 'X1 Carbon',
  ip_address: '192.168.1.100',
  serial_number: '00M09A350100001',
  access_code: '12345678',
  model: 'X1C',
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

const mockIdleStatusWithAms = {
  connected: true,
  state: 'IDLE',
  progress: 0,
  layer_num: 0,
  total_layers: 0,
  temperatures: { nozzle: 25, bed: 25, chamber: 25 },
  remaining_time: 0,
  filename: null,
  wifi_signal: -50,
  speed_level: 2,
  vt_tray: [],
  ams: [
    {
      id: 0,
      humidity: 30,
      temp: 25,
      is_ams_ht: false,
      serial_number: 'AMS00',
      sw_ver: '1.0.0',
      dry_time: 0,
      dry_status: 0,
      dry_sub_status: 0,
      dry_sf_reason: [],
      module_type: 'ams',
      tray: [
        { id: 0, ...baseTray },
        { id: 1, ...baseTray, tray_color: '00FF00FF', tray_type: 'PETG' },
        { id: 2, ...baseTray, tray_color: '0000FFFF', tray_type: 'ABS' },
        { id: 3, ...baseTray, tray_color: 'FFFF00FF', tray_type: 'TPU' },
      ],
    },
  ],
};

const mockRunningStatus = {
  ...mockIdleStatusWithAms,
  state: 'RUNNING',
};

const mockK2Printer = {
  ...mockPrinter,
  id: 2,
  name: 'K2 Plus',
  provider: 'fluidd',
  model: 'Creality K2 Plus',
};

const mockIdleStatusWithCfs = {
  ...mockIdleStatusWithAms,
  ams: [
    {
      id: 0,
      name: 'CFS T1',
      humidity: 48,
      temp: 25,
      is_ams_ht: false,
      serial_number: 'CFS001',
      sw_ver: '1.4.2',
      dry_time: 0,
      dry_status: 0,
      dry_sub_status: 0,
      dry_sf_reason: [],
      module_type: 'cfs',
      tray: [
        { id: 0, ...baseTray, tray_uuid: 'T1A', tray_color: '#0A2989' },
        { id: 1, ...baseTray, tray_uuid: 'T1B', tray_color: '#fff014' },
        { id: 2, ...baseTray, tray_uuid: 'T1C', tray_color: '#ffffff' },
        { id: 3, ...baseTray, tray_uuid: 'T1D', tray_color: '#9ea7ae' },
      ],
    },
  ],
};

const mockIdleStatusWithK2AmsFallback = {
  ...mockIdleStatusWithAms,
  ams: [
    {
      id: 0,
      name: 'AMS-A',
      humidity: 47,
      temp: 25,
      is_ams_ht: false,
      serial_number: 'CFS001',
      sw_ver: '1.4.2',
      dry_time: 0,
      dry_status: 0,
      dry_sub_status: 0,
      dry_sf_reason: [],
      module_type: 'ams',
      tray: [
        { id: 0, ...baseTray, tray_uuid: 'T1A', tag_uid: 'rfid-like', remain: 100, tray_color: '#0A2989' },
        { id: 1, ...baseTray, tray_uuid: 'T1B', tray_color: '#fff014' },
        { id: 2, ...baseTray, tray_uuid: 'T1C', tray_color: '#ffffff' },
        { id: 3, ...baseTray, tray_uuid: 'T1D', tray_color: '#9ea7ae' },
      ],
    },
  ],
};
/** Hover-card visibility flips after an 80ms timeout — wait it out. */
async function hoverSlot(slot: Element) {
  fireEvent.mouseEnter(slot);
  await waitFor(() => {
    expect(screen.getByText('Load')).toBeInTheDocument();
  });
}

describe('PrintersPage - AMS load/unload (#891)', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([mockPrinter])),
      http.get('/api/v1/queue/', () => HttpResponse.json([])),
    );
  });

  it('Load posts to /ams/load with tray_id derived from amsId*4 + slot', async () => {
    const user = userEvent.setup();
    let captured: { tray_id: string | null } | null = null;

    server.use(
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(mockIdleStatusWithAms)),
      http.post('/api/v1/printers/:id/ams/load', ({ request }) => {
        const url = new URL(request.url);
        captured = { tray_id: url.searchParams.get('tray_id') };
        return HttpResponse.json({ success: true, message: 'Loading filament from AMS 0 slot 3' });
      }),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('filament-slot').length).toBeGreaterThan(0);
    });

    // Slot 2 (third one, slotIdx=2) → expected tray_id = 0*4 + 2 = 2
    const slots = screen.getAllByTestId('filament-slot');
    await hoverSlot(slots[2]);
    await user.click(screen.getByText('Load'));

    await waitFor(() => {
      expect(captured).not.toBeNull();
      expect(captured!.tray_id).toBe('2');
    });
  });

  it('Unload posts to /ams/unload (no body, no params)', async () => {
    const user = userEvent.setup();
    let unloadCalled = false;

    server.use(
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(mockIdleStatusWithAms)),
      http.post('/api/v1/printers/:id/ams/unload', () => {
        unloadCalled = true;
        return HttpResponse.json({ success: true, message: 'Unloading filament' });
      }),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('filament-slot').length).toBeGreaterThan(0);
    });

    const slots = screen.getAllByTestId('filament-slot');
    await hoverSlot(slots[0]);
    await user.click(screen.getByText('Unload'));

    await waitFor(() => {
      expect(unloadCalled).toBe(true);
    });
  });

  it('disables Load / Unload while the printer is RUNNING', async () => {
    server.use(
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(mockRunningStatus)),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('filament-slot').length).toBeGreaterThan(0);
    });

    // Hover to reveal the actions — they should be present but disabled
    // while the printer is running (replaces the pre-#1661 behavior where
    // the trigger button was hidden entirely).
    const slots = screen.getAllByTestId('filament-slot');
    fireEvent.mouseEnter(slots[0]);

    await waitFor(() => {
      expect(screen.getByText('Load')).toBeInTheDocument();
    });

    expect(screen.getByText('Load').closest('button')).toBeDisabled();
    expect(screen.getByText('Unload').closest('button')).toBeDisabled();
  });

  it('external spool slot exposes Load and posts tray_id=254', async () => {
    const user = userEvent.setup();
    let captured: string | null = null;

    server.use(
      http.get('/api/v1/printers/:id/status', () =>
        HttpResponse.json({
          ...mockIdleStatusWithAms,
          ams: [], // external-only
          vt_tray: [{ id: 254, ...baseTray, tray_type: 'PLA', tray_color: 'FFFFFFFF' }],
        }),
      ),
      http.post('/api/v1/printers/:id/ams/load', ({ request }) => {
        captured = new URL(request.url).searchParams.get('tray_id');
        return HttpResponse.json({ success: true, message: 'Loading filament from external spool' });
      }),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('filament-slot').length).toBeGreaterThan(0);
    });

    const slots = screen.getAllByTestId('filament-slot');
    await hoverSlot(slots[0]);
    await user.click(screen.getByText('Load'));

    await waitFor(() => {
      expect(captured).toBe('254');
    });
  });

  it('CFS slot exposes assign without unsafe RFID or unverified load controls', async () => {
    const user = userEvent.setup();

    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([mockK2Printer])),
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(mockIdleStatusWithCfs)),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getByText('CFS T1')).toBeInTheDocument();
      expect(document.querySelectorAll('[title="Slot options"]').length).toBeGreaterThan(0);
    });

    const menuButtons = document.querySelectorAll<HTMLButtonElement>('[title="Slot options"]');
    await user.click(menuButtons[1]);

    await waitFor(() => {
      expect(screen.getByText('Assign')).toBeInTheDocument();
      expect(screen.queryByText(/Re-read/i)).not.toBeInTheDocument();
      expect(screen.queryByText('Load')).not.toBeInTheDocument();
      expect(screen.queryByText('Unload')).not.toBeInTheDocument();
    });
  });

  it('K2-OpenHost CFS slot exposes Load and Unload through the BOX_* driver', async () => {
    const user = userEvent.setup();
    let loadedTray: string | null = null;
    let unloadCalled = false;
    const openHostStatus = {
      ...mockIdleStatusWithCfs,
      ams: [{ ...mockIdleStatusWithCfs.ams[0], id: 1, name: 'CFS T2', module_type: 'k2oh_cfs' }],
    };

    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([mockK2Printer])),
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(openHostStatus)),
      http.post('/api/v1/printers/:id/ams/load', ({ request }) => {
        loadedTray = new URL(request.url).searchParams.get('tray_id');
        return HttpResponse.json({ success: true, message: 'Loading filament' });
      }),
      http.post('/api/v1/printers/:id/ams/unload', () => {
        unloadCalled = true;
        return HttpResponse.json({ success: true, message: 'Unloading filament' });
      }),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getByText('CFS T2')).toBeInTheDocument();
      expect(document.querySelectorAll('[title="Slot options"]').length).toBeGreaterThan(0);
    });

    // CFS T2, fourth slot -> tray_id = 1*4 + 3 = 7
    let menuButtons = document.querySelectorAll<HTMLButtonElement>('[title="Slot options"]');
    await user.click(menuButtons[3]);
    await waitFor(() => {
      expect(screen.getByText('Load')).toBeInTheDocument();
      expect(screen.queryByText(/Re-read/i)).not.toBeInTheDocument();
    });
    await user.click(screen.getByText('Load'));
    await waitFor(() => expect(loadedTray).toBe('7'));

    menuButtons = document.querySelectorAll<HTMLButtonElement>('[title="Slot options"]');
    await user.click(menuButtons[3]);
    await waitFor(() => expect(screen.getByText('Unload')).toBeInTheDocument());
    await user.click(screen.getByText('Unload'));
    await waitFor(() => expect(unloadCalled).toBe(true));
  });

  it('K2 AMS fallback status is treated as CFS for slot controls and assignment', async () => {
    const user = userEvent.setup();

    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([mockK2Printer])),
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(mockIdleStatusWithK2AmsFallback)),
      http.get('/api/v1/inventory/spools', () => HttpResponse.json([])),
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json([])),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ spoolman_enabled: 'false', spoolman_url: '' })),
      http.get('/api/v1/settings/', () => HttpResponse.json({})),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getByText('CFS T1')).toBeInTheDocument();
      expect(document.querySelectorAll('[title="Slot options"]').length).toBeGreaterThan(0);
    });

    const menuButtons = document.querySelectorAll<HTMLButtonElement>('[title="Slot options"]');
    await user.click(menuButtons[0]);

    await waitFor(() => {
      expect(screen.getByText('Assign')).toBeInTheDocument();
      expect(screen.queryByText(/Re-read/i)).not.toBeInTheDocument();
      expect(screen.queryByText('Load')).not.toBeInTheDocument();
      expect(screen.queryByText('Unload')).not.toBeInTheDocument();
    });

    await user.click(screen.getByText('Assign'));
    expect(await screen.findByRole('heading', { name: 'Assign Spool' })).toBeInTheDocument();
    expect(await screen.findByText('Create spool from slot')).toBeInTheDocument();
  });

  it('CFS slot menu exposes assign spool so local quick-create is reachable from the printer card', async () => {
    const user = userEvent.setup();

    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([mockK2Printer])),
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(mockIdleStatusWithCfs)),
      http.get('/api/v1/inventory/spools', () => HttpResponse.json([])),
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json([])),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ spoolman_enabled: 'false', spoolman_url: '' })),
      http.get('/api/v1/settings/', () => HttpResponse.json({})),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getByText('CFS T1')).toBeInTheDocument();
      expect(document.querySelectorAll('[title="Slot options"]').length).toBeGreaterThan(0);
    });

    const menuButtons = document.querySelectorAll<HTMLButtonElement>('[title="Slot options"]');
    await user.click(menuButtons[1]);

    await waitFor(() => expect(screen.getByText('Assign')).toBeInTheDocument());
    await user.click(screen.getByText('Assign'));

    expect(await screen.findByRole('heading', { name: 'Assign Spool' })).toBeInTheDocument();
    expect(await screen.findByText('Create spool from slot')).toBeInTheDocument();
  });

  it('shows loaded-spool assignment controls when a single-spool printer is offline', async () => {
    const user = userEvent.setup();

    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([{
        ...mockPrinter,
        name: 'Core One Bench',
        provider: 'prusalink',
        model: 'Prusa CORE One',
      }])),
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json({
        ...mockIdleStatusWithAms,
        connected: false,
        ams: [],
        vt_tray: [],
        temperatures: null,
      })),
      http.get('/api/v1/inventory/spools', () => HttpResponse.json([{
        id: 77,
        material: 'PETG',
        subtype: 'Matte',
        brand: 'Polymaker',
        color_name: 'Black',
        rgba: '000000FF',
        label_weight: 1000,
        weight_used: 120,
        tag_uid: null,
        tray_uuid: null,
        slicer_filament: null,
        slicer_filament_name: null,
        archived_at: null,
      }])),
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json([])),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ spoolman_enabled: 'false', spoolman_url: '' })),
      http.get('/api/v1/settings/', () => HttpResponse.json({})),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getByText('Core One Bench')).toBeInTheDocument();
      expect(screen.getByText('Offline')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Assign' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Assign Spool' })).toBeInTheDocument();
    });
    expect(screen.getByText(/Polymaker/)).toBeInTheDocument();
  });

  it('does not offer a virtual loaded spool for an offline Bambu printer', async () => {
    server.use(
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json({
        ...mockIdleStatusWithAms,
        connected: false,
        ams: [],
        vt_tray: [],
        temperatures: null,
      })),
      http.get('/api/v1/inventory/assignments', () => HttpResponse.json([])),
      http.get('/api/v1/settings/spoolman', () => HttpResponse.json({ spoolman_enabled: 'false', spoolman_url: '' })),
      http.get('/api/v1/settings/', () => HttpResponse.json({})),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getByText('X1 Carbon')).toBeInTheDocument();
      expect(screen.getByText('Offline')).toBeInTheDocument();
    });

    expect(screen.queryByText('Loaded spool')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Assign' })).not.toBeInTheDocument();
  });

  it('an AMS-HT slot loads and unloads by its unit id (128), not unit*4+slot', async () => {
    const user = userEvent.setup();
    const captured: Record<string, string | null> = {};
    const htStatus = {
      ...mockIdleStatusWithAms,
      ams: [
        {
          ...mockIdleStatusWithAms.ams[0],
          id: 128,
          is_ams_ht: true,
          serial_number: 'HT00',
          module_type: 'n3s',
          tray: [{ id: 0, ...baseTray }],
        },
      ],
    };

    server.use(
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(htStatus)),
      http.post('/api/v1/printers/:id/ams/load', ({ request }) => {
        captured.load = new URL(request.url).searchParams.get('tray_id');
        return HttpResponse.json({ success: true, message: 'Loading filament from AMS HT-A' });
      }),
      http.post('/api/v1/printers/:id/ams/unload', ({ request }) => {
        captured.unload = new URL(request.url).searchParams.get('tray_id');
        return HttpResponse.json({ success: true, message: 'Unloading filament' });
      }),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('filament-slot').length).toBeGreaterThan(0);
    });

    await hoverSlot(screen.getAllByTestId('filament-slot')[0]);
    await user.click(screen.getByText('Load'));
    await waitFor(() => expect(captured.load).toBe('128'));

    await hoverSlot(screen.getAllByTestId('filament-slot')[0]);
    await user.click(screen.getByText('Unload'));
    await waitFor(() => expect(captured.unload).toBe('128'));
  });

  it('with a Filament Track Switch, an AMS-HT slot asks which nozzle and sends it', async () => {
    const user = userEvent.setup();
    let captured: { tray_id: string | null; extruder_id: string | null } | null = null;
    const htStatus = {
      ...mockIdleStatusWithAms,
      fila_switch: { installed: true, ready: true, in_slots: [-1, -1], out_extruders: [1, 0], stat: 0, info: 0 },
      extruder_slots: {},
      ams: [
        {
          ...mockIdleStatusWithAms.ams[0],
          id: 128,
          is_ams_ht: true,
          serial_number: 'HT00',
          module_type: 'n3s',
          tray: [{ id: 0, ...baseTray }],
        },
      ],
    };

    server.use(
      http.get('/api/v1/printers/:id/status', () => HttpResponse.json(htStatus)),
      http.post('/api/v1/printers/:id/ams/load', ({ request }) => {
        const url = new URL(request.url);
        captured = { tray_id: url.searchParams.get('tray_id'), extruder_id: url.searchParams.get('extruder_id') };
        return HttpResponse.json({ success: true, message: 'Loading filament from AMS HT-A' });
      }),
    );

    render(<PrintersPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('filament-slot').length).toBeGreaterThan(0);
    });

    await hoverSlot(screen.getAllByTestId('filament-slot')[0]);
    await user.click(screen.getByText('Load'));
    await user.click(await screen.findByText('Left nozzle'));
    await user.click(screen.getByText('Confirm'));

    await waitFor(() => {
      expect(captured).toEqual({ tray_id: '128', extruder_id: '1' });
    });
  });
});
