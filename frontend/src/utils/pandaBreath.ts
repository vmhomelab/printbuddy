import type { PandaBreathStatus } from '../api/client';

export function parsePandaBreathAssignments(value?: string | null): Record<string, number> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .map(([deviceId, printerId]) => [deviceId, Number(printerId)] as const)
        .filter(([deviceId, printerId]) => deviceId.trim().length > 0 && Number.isFinite(printerId) && printerId > 0)
    );
  } catch {
    return {};
  }
}

export function stringifyPandaBreathAssignments(assignments: Record<string, number>): string {
  const cleaned = Object.fromEntries(
    Object.entries(assignments)
      .filter(([deviceId, printerId]) => deviceId.trim().length > 0 && Number.isFinite(printerId) && printerId > 0)
      .sort(([a], [b]) => a.localeCompare(b))
  );
  return JSON.stringify(cleaned);
}

export function getPandaBreathDevices(status?: PandaBreathStatus | null): Record<string, PandaBreathStatus['state']> {
  if (status?.devices && Object.keys(status.devices).length > 0) {
    return status.devices;
  }
  const deviceId = status?.device_id || status?.state?.device_id;
  if (deviceId && status?.state) {
    return { [deviceId]: status.state };
  }
  return {};
}

export function getAssignedPandaBreathState(
  printerId: number,
  assignmentJson?: string | null,
  status?: PandaBreathStatus | null
): PandaBreathStatus['state'] | null {
  const assignments = parsePandaBreathAssignments(assignmentJson);
  const devices = getPandaBreathDevices(status);
  const matched = Object.entries(assignments).find(([, assignedPrinterId]) => assignedPrinterId === printerId);
  if (!matched) return null;
  return devices[matched[0]] || null;
}
