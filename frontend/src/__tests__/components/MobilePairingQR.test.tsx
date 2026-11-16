import { describe, expect, it, vi } from 'vitest';

// Capture what the QR encodes; the SVG itself is qrcode.react's business.
const qrValues: string[] = [];
vi.mock('qrcode.react', () => ({
  QRCodeSVG: (props: { value: string; 'aria-label'?: string }) => {
    qrValues.push(props.value);
    return <svg role="img" aria-label={props['aria-label']} />;
  },
}));

import { render, screen, waitFor } from '../utils';
import { MobilePairingQR } from '../../components/MobilePairingQR';
import { buildPairingUri, isLocalOnly } from '../../utils/mobilePairing';

const KEY = 'bb_AbCdEf123456-_xyz';

describe('buildPairingUri', () => {
  it('encodes server and key in the format the mobile app reads', () => {
    // Must match parsePairingPayload in vmhomelab/printbuddy-mobile-app (src/lib/pairing.ts).
    expect(buildPairingUri('https://pb.example.com/sub', KEY)).toBe(
      `printbuddy://pair?server=https%3A%2F%2Fpb.example.com%2Fsub&key=${KEY}`,
    );
  });
});

describe('isLocalOnly', () => {
  it('flags loopback addresses only', () => {
    expect(isLocalOnly('http://localhost:8000')).toBe(true);
    expect(isLocalOnly('http://127.0.0.1')).toBe(true);
    expect(isLocalOnly('http://192.168.1.10:8000')).toBe(false);
    expect(isLocalOnly('not a url')).toBe(false);
  });
});

describe('MobilePairingQR', () => {
  it('renders a QR image for the pairing link and shows the server address', async () => {
    render(<MobilePairingQR apiKey={KEY} serverUrl="http://192.168.1.10:8000" />);
    await screen.findByRole('img');
    // The QR encodes exactly the pairing link.
    expect(qrValues.at(-1)).toBe(buildPairingUri('http://192.168.1.10:8000', KEY));
    expect(screen.getByText('http://192.168.1.10:8000')).toBeInTheDocument();
  });

  it('warns when the page was opened via localhost', async () => {
    render(<MobilePairingQR apiKey={KEY} serverUrl="http://localhost:8000" />);
    await waitFor(() => expect(screen.getByTestId('mobile-pairing-qr').textContent).toMatch(/localhost|computer|Computer/));
    expect(screen.getByTestId('mobile-pairing-qr').querySelector('.text-yellow-500')).not.toBeNull();
  });

  it('shows no warning for a network address', async () => {
    render(<MobilePairingQR apiKey={KEY} serverUrl="http://printbuddy.lan" />);
    await screen.findByRole('img');
    expect(screen.getByTestId('mobile-pairing-qr').querySelector('.text-yellow-500')).toBeNull();
  });
});
