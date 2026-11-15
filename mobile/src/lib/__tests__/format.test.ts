import assert from 'node:assert/strict';
import { test } from 'node:test';

import { clampProgress, formatEta, formatRemaining, formatTemp, isJobActive, jobName, stateKey, stateTone } from '../format.ts';

test('stateKey maps backend states and treats disconnected as offline', () => {
  assert.equal(stateKey(undefined), 'offline');
  assert.equal(stateKey({ connected: false, state: 'RUNNING' }), 'offline');
  assert.equal(stateKey({ connected: true, state: 'RUNNING' }), 'printing');
  assert.equal(stateKey({ connected: true, state: 'PAUSE' }), 'paused');
  assert.equal(stateKey({ connected: true, state: 'FINISH' }), 'finished');
  assert.equal(stateKey({ connected: true, state: 'FAILED' }), 'failed');
  assert.equal(stateKey({ connected: true, state: null }), 'idle');
  assert.equal(stateKey({ connected: true, state: 'prepare' }), 'preparing');
  assert.equal(stateKey({ connected: true, state: 'SOMETHING_NEW' }), 'unknown');
});

test('job activity and tones', () => {
  assert.equal(isJobActive('printing'), true);
  assert.equal(isJobActive('paused'), true);
  assert.equal(isJobActive('finished'), false);
  assert.equal(stateTone('failed'), 'error');
  assert.equal(stateTone('idle'), 'idle');
});

test('clampProgress', () => {
  assert.equal(clampProgress(null), 0);
  assert.equal(clampProgress(Number.NaN), 0);
  assert.equal(clampProgress(-3), 0);
  assert.equal(clampProgress(150), 100);
  assert.equal(clampProgress(42.5), 42.5);
});

test('formatRemaining takes minutes', () => {
  assert.equal(formatRemaining(null), null);
  assert.equal(formatRemaining(0), null);
  assert.equal(formatRemaining(45), '45 min');
  assert.equal(formatRemaining(125), '2 h 05 min');
});

test('formatEta adds minutes to now', () => {
  const now = new Date(2026, 0, 1, 12, 0, 0);
  assert.equal(formatEta(90, now, 'de-DE'), '13:30');
  assert.equal(formatEta(null, now), null);
});

test('formatTemp shows target only when heating', () => {
  assert.equal(formatTemp(undefined), null);
  assert.equal(formatTemp(24.6), '25°');
  assert.equal(formatTemp(24.6, 0), '25°');
  assert.equal(formatTemp(180.2, 220), '180° / 220°');
});

test('jobName prefers subtask name and strips extensions', () => {
  assert.equal(jobName({ connected: true, state: 'RUNNING', subtask_name: 'Benchy', gcode_file: 'x.gcode' }), 'Benchy');
  assert.equal(jobName({ connected: true, state: 'RUNNING', gcode_file: 'plate_1.gcode.3mf' }), 'plate_1.gcode');
  assert.equal(jobName({ connected: true, state: 'RUNNING', current_print: 'Part.3mf' }), 'Part');
  assert.equal(jobName({ connected: true, state: 'IDLE' }), null);
});
