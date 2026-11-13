import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { render } from '../utils';
import { VirtualPrinterList } from '../../components/VirtualPrinterList';

vi.mock('../../api/client', () => ({
  api: {
    getSettings: vi.fn().mockResolvedValue({}),
  },
  multiVirtualPrinterApi: {
    list: vi.fn().mockResolvedValue({ printers: [], models: {} }),
    getCaCertificate: vi.fn().mockResolvedValue({
      pem: '-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----',
      fingerprint_sha256: 'AA:BB:CC',
    }),
  },
  virtualPrinterApi: {
    getSettings: vi.fn().mockResolvedValue({ archive_name_source: 'metadata' }),
    updateSettings: vi.fn().mockResolvedValue({ archive_name_source: 'metadata' }),
  },
}));

vi.mock('../../components/VirtualPrinterCard', () => ({
  VirtualPrinterCard: () => <div data-testid="virtual-printer-card" />,
}));

vi.mock('../../components/VirtualPrinterAddDialog', () => ({
  VirtualPrinterAddDialog: ({ onClose }: { onClose: () => void }) => (
    <button type="button" onClick={onClose}>Mock add dialog</button>
  ),
}));

describe('VirtualPrinterList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('presents both virtual printer types (#52)', async () => {
    render(<VirtualPrinterList />);

    await waitFor(() => {
      expect(screen.getByText('Two kinds of virtual printers')).toBeInTheDocument();
    });

    expect(screen.getByText('Bambu-compatible')).toBeInTheDocument();
    expect(screen.getByText('Moonraker/OctoPrint-compatible')).toBeInTheDocument();
    expect(screen.getByText('Setup required:')).toBeInTheDocument();
    expect(screen.getByText('No extra setup:')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Read the setup guide/ })).toHaveAttribute('target', '_blank');
    // The old "Bambu Lab only" warning would turn away non-Bambu users.
    expect(screen.queryByText('Bambu Lab only')).not.toBeInTheDocument();
  });

  it('marks the slicer certificate as Bambu-only', async () => {
    render(<VirtualPrinterList />);

    await waitFor(() => {
      expect(screen.getByText('Bambu-compatible only')).toBeInTheDocument();
    });
  });
});
