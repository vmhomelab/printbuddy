import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { KlipperControlPanel } from '../../components/KlipperControlPanel';
import { api } from '../../api/client';
import type { Printer } from '../../api/client';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      axisJog: vi.fn(),
      homeAxes: vi.fn(),
      extrude: vi.fn(),
      klipperHome: vi.fn(),
      klipperExtrude: vi.fn(),
      setNozzleTemperature: vi.fn(),
      setBedTemperature: vi.fn(),
      setChamberTemperature: vi.fn(),
      disableSteppers: vi.fn(),
    },
  };
});

const prusaPrinter = {
  id: 3,
  name: 'Prusa MK4S',
  ip_address: '192.168.1.246',
  serial_number: 'PRUSA-3',
  access_code: '',
  model: 'Prusa MK4S',
  provider: 'prusalink',
  enabled: true,
  nozzle_diameter: 0.4,
  nozzle_type: 'brass',
  location: null,
  auto_archive: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as Printer;

const fluiddPrinter = {
  ...prusaPrinter,
  id: 7,
  name: 'Creality K2 Plus',
  model: 'Creality K2 Plus',
  provider: 'fluidd',
} as Printer;

describe('KlipperControlPanel PrusaLink controls', () => {
  beforeEach(() => {
    vi.mocked(api.axisJog).mockResolvedValue({ success: true, message: 'ok' });
    vi.mocked(api.homeAxes).mockResolvedValue({ success: true, message: 'ok' });
    vi.mocked(api.extrude).mockResolvedValue({ success: true, message: 'ok' });
    vi.mocked(api.klipperHome).mockResolvedValue({ success: true });
    vi.mocked(api.klipperExtrude).mockResolvedValue({ success: true });
    vi.mocked(api.disableSteppers).mockResolvedValue({ success: true, message: 'ok' });
    vi.clearAllMocks();
  });

  it('uses provider-neutral home endpoint for PrusaLink home controls', async () => {
    const user = userEvent.setup();

    render(<KlipperControlPanel printer={prusaPrinter} status={{ connected: true }} showToast={vi.fn()} />);

    await user.click(screen.getByTitle('Home All'));

    await waitFor(() => expect(api.homeAxes).toHaveBeenCalledWith(3, 'all'));
    expect(api.klipperHome).not.toHaveBeenCalled();
  });

  it('uses provider-neutral extrude endpoint for PrusaLink extrusion controls', async () => {
    const user = userEvent.setup();

    render(<KlipperControlPanel printer={prusaPrinter} status={{ connected: true }} showToast={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: /extrude/i }));

    await waitFor(() => expect(api.extrude).toHaveBeenCalledWith(3, 10, 300));
    expect(api.klipperExtrude).not.toHaveBeenCalled();
  });

  it('shows generic Klipper manual controls and disables steppers for Fluidd printers', async () => {
    const user = userEvent.setup();

    render(<KlipperControlPanel printer={fluiddPrinter} status={{ connected: true }} showToast={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: /disable steppers/i }));

    await waitFor(() => expect(api.disableSteppers).toHaveBeenCalledWith(7));
  });
});

describe('KlipperControlPanel chamber heater controls', () => {
  const qidiPrinter = { ...fluiddPrinter, id: 9, name: 'QIDI Q2', model: 'Generic Klipper Printer', provider: 'klipper' } as Printer;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.setChamberTemperature).mockResolvedValue({ success: true, message: 'ok' });
  });

  it('hides the chamber row when no chamber heater is detected', () => {
    render(<KlipperControlPanel printer={qidiPrinter} status={{ connected: true }} showToast={vi.fn()} />);

    expect(screen.queryByLabelText('Chamber temperature target')).not.toBeInTheDocument();
  });

  it('sets the chamber target and rejects values above the printer limit', async () => {
    const user = userEvent.setup();
    const showToast = vi.fn();
    render(
      <KlipperControlPanel
        printer={qidiPrinter}
        status={{
          connected: true,
          chamber_heater_supported: true,
          chamber_temp_max: 70,
          temperatures: { nozzle: 25, bed: 24, chamber: 31, chamber_target: 0 },
        }}
        showToast={showToast}
      />
    );

    const input = screen.getByLabelText('Chamber temperature target');
    await user.type(input, '90');
    await user.click(screen.getByRole('button', { name: 'Chamber' }));
    expect(api.setChamberTemperature).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(expect.any(String), 'error');

    await user.clear(input);
    await user.type(input, '0');
    await user.click(screen.getByRole('button', { name: 'Chamber' }));
    await waitFor(() => expect(api.setChamberTemperature).toHaveBeenCalledWith(9, 0));
  });
});
