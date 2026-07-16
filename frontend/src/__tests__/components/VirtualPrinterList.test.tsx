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

  it('marks virtual-printer settings as Bambu Lab only', async () => {
    render(<VirtualPrinterList />);

    await waitFor(() => {
      expect(screen.getByText('Bambu Lab only')).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Virtual printers emulate the Bambu LAN protocol/i)
    ).toBeInTheDocument();
  });
});
