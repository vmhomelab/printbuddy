import type { Printer } from '../api/client';

/** Name of the camera Prusa Connect Local declared for this printer, if one was picked up. */
export function prusaConnectLocalCameraName(printer: Pick<Printer, 'provider' | 'provider_options'>): string | null {
  if (printer.provider !== 'prusaconnectlocal' || !printer.provider_options) return null;
  try {
    const options = JSON.parse(printer.provider_options) as { pcl_camera?: unknown };
    return typeof options.pcl_camera === 'string' && options.pcl_camera ? options.pcl_camera : null;
  } catch {
    return null;
  }
}

export function canOpenPrinterCamera(
  printer: Pick<Printer, 'provider' | 'provider_options' | 'external_camera_enabled' | 'external_camera_url'>,
  isConnected: boolean | undefined,
  canViewCamera: boolean,
): boolean {
  if (!canViewCamera) return false;

  const hasExternalCamera = Boolean(printer.external_camera_enabled && printer.external_camera_url?.trim());
  if (hasExternalCamera) return true;

  // Prusa Connect Local serves the camera itself (declared on the server, picked
  // up when the printer was added); the backend proxies it with the API key.
  if (prusaConnectLocalCameraName(printer)) return true;

  // Elegoo SDCP Centauri Carbon exposes a native MJPEG stream on :3031/video.
  // The API normally derives this as an external-camera URL, but allow the
  // action for connected Elegoo printers even if a stale client object has not
  // received the derived fields yet.
  if (printer.provider === 'elegoo_sdcp') return Boolean(isConnected);

  // Bambu printers have a native camera endpoint. Moonraker/Klipper API URLs
  // are control endpoints, not camera streams; those printers need the configured
  // Camera URL from add/edit settings so the normal Printbuddy camera viewer can
  // render it like Bambu camera windows do.
  return printer.provider === 'bambu' && Boolean(isConnected);
}
