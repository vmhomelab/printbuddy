/**
 * Tests for the OctoEverywhere Gadget failure-detection settings (PB-35).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { OctoEverywhereDetectionSettings } from '../../components/OctoEverywhereDetectionSettings';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

const authState = vi.hoisted(() => ({ canUpdate: true }));

vi.mock('../../contexts/AuthContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../contexts/AuthContext')>();
  return {
    ...actual,
    useAuth: () => ({
      ...actual.useAuth(),
      hasPermission: (permission: string) => permission !== 'settings:update' || authState.canUpdate,
    }),
  };
});

const baseSettings = {
  enabled: false,
  has_api_key: false,
  sensitivity: 'medium',
  action: 'notify',
  poll_interval: 0,
  enabled_printers: null,
  notify_on_warning: true,
};

const baseStatus = {
  is_running: true,
  last_error: null,
  account_error: null,
  per_printer: {},
  history: [],
  enabled: false,
  has_api_key: false,
};

const printers = [
  { id: 1, name: 'X1C' },
  { id: 2, name: 'Voron' },
];

describe('OctoEverywhereDetectionSettings', () => {
  beforeEach(() => {
    authState.canUpdate = true;
    server.use(
      http.get('/api/v1/octoeverywhere/settings', () => HttpResponse.json(baseSettings)),
      http.get('/api/v1/octoeverywhere/status', () => HttpResponse.json(baseStatus)),
      http.get('/api/v1/printers', () => HttpResponse.json(printers)),
    );
  });

  it('renders the provider card with privacy note and key link', async () => {
    render(<OctoEverywhereDetectionSettings />);
    expect(await screen.findByText('OctoEverywhere AI detection')).toBeInTheDocument();
    expect(screen.getByText(/uploaded to OctoEverywhere's servers/i)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /get a free api key/i });
    expect(link).toHaveAttribute('href', 'https://octoeverywhere.com/gadgetapi');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('saves settings including the new key and a printer subset', async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.put('/api/v1/octoeverywhere/settings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...baseSettings, has_api_key: true, enabled_printers: [2] });
      }),
    );
    const user = userEvent.setup();
    render(<OctoEverywhereDetectionSettings />);

    const keyInput = await screen.findByLabelText('Gadget API key');
    await user.type(keyInput, ' prod_ABC ');
    await user.selectOptions(screen.getByLabelText(/Action when Gadget suggests a pause/i), 'pause');
    await user.selectOptions(screen.getByLabelText('Inspection interval'), '30');
    await user.click(screen.getByLabelText(/Monitor all connected printers/i));
    await user.click(await screen.findByLabelText('X1C'));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({
      api_key: 'prod_ABC',
      action: 'pause',
      poll_interval: 30,
      enabled_printers: [2],
    });
    expect(body).not.toHaveProperty('all_printers');
  });

  it('does not send the key field when no new key was typed', async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get('/api/v1/octoeverywhere/settings', () => HttpResponse.json({ ...baseSettings, has_api_key: true })),
      http.put('/api/v1/octoeverywhere/settings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...baseSettings, has_api_key: true, sensitivity: 'high' });
      }),
    );
    const user = userEvent.setup();
    render(<OctoEverywhereDetectionSettings />);

    expect(await screen.findByPlaceholderText(/A key is stored/i)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Sensitivity'), 'high');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).not.toHaveProperty('api_key');
    expect(body).toMatchObject({ sensitivity: 'high', all_printers: true });
  });

  it('tests the stored key and shows the error type message', async () => {
    let testBody: unknown = 'unset';
    server.use(
      http.get('/api/v1/octoeverywhere/settings', () => HttpResponse.json({ ...baseSettings, has_api_key: true })),
      http.post('/api/v1/octoeverywhere/test-connection', async ({ request }) => {
        testBody = await request.json();
        return HttpResponse.json({ ok: false, error_type: 'OE_INVALID_API_KEY', error: 'OE_INVALID_API_KEY: bad key' });
      }),
    );
    const user = userEvent.setup();
    render(<OctoEverywhereDetectionSettings />);

    await user.click(await screen.findByRole('button', { name: 'Test' }));
    expect(await screen.findByText('OE_INVALID_API_KEY: bad key')).toBeInTheDocument();
    expect(testBody).toEqual({});
  });

  it('warns when enabled without a key', async () => {
    server.use(
      http.get('/api/v1/octoeverywhere/settings', () => HttpResponse.json({ ...baseSettings, enabled: true })),
    );
    render(<OctoEverywhereDetectionSettings />);
    expect(await screen.findByText(/no API key is stored/i)).toBeInTheDocument();
  });

  it('shows per-printer results, account errors and history', async () => {
    server.use(
      http.get('/api/v1/octoeverywhere/status', () =>
        HttpResponse.json({
          ...baseStatus,
          account_error: 'OE_FREE_USAGE_LIMIT_REACHED',
          per_printer: {
            '1': {
              print_quality: 3,
              score: 70,
              warning: true,
              pause: false,
              frame_count: 4,
              last_checked: '2026-11-10T10:00:00Z',
              next_check_in: 12,
              using_fallback: false,
              stopped_reason: null,
              last_issue: null,
            },
            '2': {
              print_quality: null,
              score: null,
              warning: false,
              pause: false,
              frame_count: 0,
              last_checked: null,
              next_check_in: 50,
              using_fallback: false,
              stopped_reason: null,
              last_issue: 'no_camera',
            },
          },
          history: [
            {
              printer_id: 1,
              task_name: 'benchy.3mf',
              timestamp: '2026-11-10T10:00:00Z',
              print_quality: 1,
              score: 95,
              warning: true,
              pause: true,
            },
          ],
        }),
      ),
    );
    render(<OctoEverywhereDetectionSettings />);
    expect(await screen.findByText(/paused inspections: OE_FREE_USAGE_LIMIT_REACHED/)).toBeInTheDocument();
    expect(await screen.findByText(/Quality 3\/10 · warning/)).toBeInTheDocument();
    expect(screen.getByText('No camera available')).toBeInTheDocument();
    expect(screen.getByText('pause suggested')).toBeInTheDocument();
  });

  it('is read-only without settings:update permission', async () => {
    authState.canUpdate = false;
    server.use(
      http.get('/api/v1/octoeverywhere/settings', () => HttpResponse.json({ ...baseSettings, has_api_key: true })),
    );
    render(<OctoEverywhereDetectionSettings />);
    expect(await screen.findByLabelText('Gadget API key')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.queryByText('Remove stored key')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Test' })).toBeDisabled();
  });
});
