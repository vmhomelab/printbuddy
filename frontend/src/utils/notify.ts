// Notify! group (GRP) and browser (WB) device IDs receive text notifications only.
export const isNotifyPhotoUnsupported = (deviceId: string) => /^(GRP|WB)/i.test(deviceId.trim());

// Printbuddy's Notify provider sends to a list of recipients (config.recipients),
// with a single top-level device_id kept only by legacy configs. Photos are
// unavailable as soon as one enabled recipient cannot receive them.
export const notifyRecipientsPhotoUnsupported = (config: Record<string, unknown> | null | undefined): boolean => {
  if (!config) return false;
  const recipients = config.recipients;
  if (Array.isArray(recipients)) {
    return recipients.some((recipient) => !!recipient
      && typeof recipient === 'object'
      && (recipient as Record<string, unknown>).enabled !== false
      && isNotifyPhotoUnsupported(String((recipient as Record<string, unknown>).device_id || '')));
  }
  return isNotifyPhotoUnsupported(String(config.device_id || ''));
};
