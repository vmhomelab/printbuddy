import { describe, expect, it } from 'vitest';
import { canOpenPrinterCamera } from '../../utils/printerCamera';

describe('PrintersPage camera action', () => {
  it('allows a Moonraker printer camera only when an external camera URL is configured', () => {
    const moonrakerPrinter = {
      provider: 'moonraker',
      external_camera_enabled: true,
      external_camera_url: 'http://10.17.10.31/webcam/?action=stream',
    };

    expect(canOpenPrinterCamera(moonrakerPrinter, false, true)).toBe(true);
  });

  it('does not treat the Moonraker/API URL as a camera target', () => {
    const moonrakerPrinter = {
      provider: 'moonraker',
      api_url: 'http://10.17.10.31:7125',
      external_camera_enabled: false,
      external_camera_url: null,
    };

    expect(canOpenPrinterCamera(moonrakerPrinter, true, true)).toBe(false);
  });

  it('keeps Bambu built-in camera available when the printer is connected', () => {
    const bambuPrinter = {
      provider: 'bambu',
      external_camera_enabled: false,
      external_camera_url: null,
    };

    expect(canOpenPrinterCamera(bambuPrinter, true, true)).toBe(true);
  });
});
