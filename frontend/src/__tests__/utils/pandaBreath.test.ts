import { describe, expect, it } from 'vitest';
import { getAssignedPandaBreathState, parsePandaBreathAssignments, stringifyPandaBreathAssignments } from '../../utils/pandaBreath';
import type { PandaBreathStatus } from '../../api/client';

describe('pandaBreath helpers', () => {
  it('parses and cleans printer assignment JSON', () => {
    expect(parsePandaBreathAssignments('{"DEVICE_B":"2","DEVICE_A":1,"bad":"x"}')).toEqual({
      DEVICE_B: 2,
      DEVICE_A: 1,
    });
    expect(parsePandaBreathAssignments('not-json')).toEqual({});
  });

  it('returns assigned device state for the matching printer only', () => {
    const status: PandaBreathStatus = {
      enabled: true,
      connected: true,
      broker: 'mqtt.local',
      port: 1883,
      topic_prefix: 'panda_breath',
      state: {},
      devices: {
        DEVICE_A: { device_id: 'DEVICE_A', chamber_actual: 31.2, chamber_target: 45, mode: 'auto mode' },
        DEVICE_B: { device_id: 'DEVICE_B', chamber_actual: 42.8, chamber_target: 55, mode: 'filament drying' },
      },
    };

    expect(getAssignedPandaBreathState(2, '{"DEVICE_A":1,"DEVICE_B":2}', status)?.chamber_actual).toBe(42.8);
    expect(getAssignedPandaBreathState(3, '{"DEVICE_A":1,"DEVICE_B":2}', status)).toBeNull();
  });

  it('serializes assignments deterministically', () => {
    expect(stringifyPandaBreathAssignments({ DEVICE_B: 2, DEVICE_A: 1, invalid: 0 })).toBe('{"DEVICE_A":1,"DEVICE_B":2}');
  });
});
