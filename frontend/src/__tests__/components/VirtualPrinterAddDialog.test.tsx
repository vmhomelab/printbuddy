/**
 * Tests for VirtualPrinterAddDialog: choosing the Moonraker/OctoPrint-compatible
 * printer type (#52).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { VirtualPrinterAddDialog } from '../../components/VirtualPrinterAddDialog';

vi.mock('../../api/client', () => ({
  multiVirtualPrinterApi: {
    create: vi.fn().mockResolvedValue({}),
  },
  api: {
    getSettings: vi.fn().mockResolvedValue({}),
    getPrinters: vi.fn().mockResolvedValue([
      { id: 1, name: 'X1C', ip_address: '10.0.0.1', provider: 'bambu' },
      { id: 2, name: 'Snapmaker U1', ip_address: '10.0.0.2', provider: 'klipper' },
    ]),
  },
}));

import { multiVirtualPrinterApi } from '../../api/client';

describe('VirtualPrinterAddDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates a Bambu-compatible VP by default', async () => {
    const user = userEvent.setup();
    render(<VirtualPrinterAddDialog onClose={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(multiVirtualPrinterApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ protocol: 'bambu', mode: 'immediate' }),
      );
    });
  });

  it('hides proxy mode and offers only non-Bambu targets for Moonraker VPs', async () => {
    const user = userEvent.setup();
    render(<VirtualPrinterAddDialog onClose={vi.fn()} />);

    expect(screen.getByText('Proxy')).toBeInTheDocument();
    await user.click(screen.getByText('Moonraker/OctoPrint-compatible'));
    expect(screen.queryByText('Proxy')).not.toBeInTheDocument();

    await user.click(screen.getByText('Queue'));
    const select = await screen.findByRole('combobox');
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /Snapmaker U1/ })).toBeInTheDocument();
    });
    expect(screen.queryByRole('option', { name: /X1C/ })).not.toBeInTheDocument();

    await user.selectOptions(select, '2');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(multiVirtualPrinterApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ protocol: 'moonraker', mode: 'print_queue', target_printer_id: 2 }),
      );
    });
  });
});
