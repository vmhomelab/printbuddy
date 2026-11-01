import { describe, expect, it } from 'vitest';
import { canOpenPrinterCamera, prusaConnectLocalCameraName } from '../../utils/printerCamera';

const pcl = (options: object | string | null) => ({
  provider: 'prusaconnectlocal' as const,
  provider_options: options === null || typeof options === 'string' ? options : JSON.stringify(options),
  external_camera_enabled: false,
  external_camera_url: null,
});

describe('Prusa Connect Local cameras', () => {
  it('opens the camera a printer picked up from Prusa Connect Local', () => {
    const printer = pcl({ pcl_device_id: 'dev', pcl_camera: 'core-cam' });
    expect(prusaConnectLocalCameraName(printer)).toBe('core-cam');
    expect(canOpenPrinterCamera(printer, false, true)).toBe(true);
  });

  it('has no camera without a declared one or with broken options', () => {
    expect(canOpenPrinterCamera(pcl({ pcl_device_id: 'dev' }), true, true)).toBe(false);
    expect(prusaConnectLocalCameraName(pcl('{not json'))).toBeNull();
    expect(prusaConnectLocalCameraName(pcl(null))).toBeNull();
  });

  it('still respects the camera:view permission', () => {
    expect(canOpenPrinterCamera(pcl({ pcl_camera: 'core-cam' }), true, false)).toBe(false);
  });

  it('ignores pcl options on other providers', () => {
    const printer = { ...pcl({ pcl_camera: 'core-cam' }), provider: 'prusalink' as const };
    expect(prusaConnectLocalCameraName(printer)).toBeNull();
  });
});
