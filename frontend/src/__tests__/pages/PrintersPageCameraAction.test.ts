import { describe, expect, it } from 'vitest';
import { canOpenPrinterCamera } from '../../utils/printerCamera';

describe('PrintersPage camera action', () => {
  it('allows a Moonraker printer camera only when an external camera URL is configured', () => {
    const moonrakerPrinter = {
      provider: 'klipper' as const,
      external_camera_enabled: true,
      external_camera_url: 'http://10.17.10.31/webcam/?action=stream',
    };

    expect(canOpenPrinterCamera(moonrakerPrinter, false, true)).toBe(true);
  });

  it('does not treat the Moonraker/API URL as a camera target', () => {
    const moonrakerPrinter = {
      provider: 'klipper' as const,
      api_url: 'http://10.17.10.31:7125',
      external_camera_enabled: false,
      external_camera_url: null,
    };

    expect(canOpenPrinterCamera(moonrakerPrinter, true, true)).toBe(false);
  });

  it('keeps Bambu built-in camera available when the printer is connected', () => {
    const bambuPrinter = {
      provider: 'bambu' as const,
      external_camera_enabled: false,
      external_camera_url: null,
    };

    expect(canOpenPrinterCamera(bambuPrinter, true, true)).toBe(true);
  });

  it('allows connected Elegoo SDCP printers to use the derived native MJPEG camera', () => {
    const elegooPrinter = {
      provider: 'elegoo_sdcp' as const,
      external_camera_enabled: false,
      external_camera_url: null,
    };

    expect(canOpenPrinterCamera(elegooPrinter, true, true)).toBe(true);
    expect(canOpenPrinterCamera(elegooPrinter, false, true)).toBe(false);
  });

  it('allows PrusaLink cameras when the API response exposes an effective camera URL', () => {
    const prusaLinkPrinter = {
      provider: 'prusalink' as const,
      external_camera_enabled: true,
      external_camera_url: 'http://10.17.10.50:8080/?action=stream',
    };

    expect(canOpenPrinterCamera(prusaLinkPrinter, false, true)).toBe(true);
  });
});
