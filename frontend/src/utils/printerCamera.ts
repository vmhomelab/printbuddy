import type { Printer } from '../api/client';

export function canOpenPrinterCamera(
  printer: Pick<Printer, 'provider' | 'external_camera_enabled' | 'external_camera_url'>,
  isConnected: boolean | undefined,
  canViewCamera: boolean,
): boolean {
  if (!canViewCamera) return false;

  const hasExternalCamera = Boolean(printer.external_camera_enabled && printer.external_camera_url?.trim());
  if (hasExternalCamera) return true;

  // Bambu printers have a native camera endpoint. Moonraker/Klipper API URLs
  // are control endpoints, not camera streams; those printers need the configured
  // Camera URL from add/edit settings so the normal Printbuddy camera viewer can
  // render it like Bambu camera windows do.
  return printer.provider === 'bambu' && Boolean(isConnected);
}
