/**
 * Tests for adding an OctoPrint printer (#34).
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { PrintersPage } from '../../pages/PrintersPage';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

async function openOctoPrintForm() {
  const user = userEvent.setup();
  render(<PrintersPage />);
  await user.click(await screen.findByText(/add printer/i));
  await user.selectOptions(await screen.findByLabelText('Printer type'), 'octoprint');
  await user.type(screen.getByPlaceholderText('My Printer'), 'Ender 3');
  await user.type(screen.getByLabelText('OctoPrint URL'), 'octopi.local');
  await user.type(screen.getByLabelText('OctoPrint API key'), 'ABCDEF');
  const submit = screen
    .getAllByRole('button', { name: /add printer/i })
    .find((b) => b.getAttribute('type') === 'submit')!;
  return { user, submit };
}

describe('AddPrinterModal OctoPrint', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/printers/', () => HttpResponse.json([])),
      http.get('/api/v1/queue/', () => HttpResponse.json([])),
      http.get('/api/v1/discovery/info', () =>
        HttpResponse.json({ is_docker: false, ssdp_running: false, scan_running: false, subnets: [] }),
      ),
    );
  });

  it('derives the host from the OctoPrint URL and adds http:// when missing', async () => {
    let payload: Record<string, unknown> | null = null;
    server.use(
      http.post('/api/v1/printers/', async ({ request }) => {
        payload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 12, name: 'Ender 3' });
      }),
    );

    const { user, submit } = await openOctoPrintForm();
    expect(screen.queryByPlaceholderText('01P00A000000000')).not.toBeInTheDocument();
    // OctoPrint is configured by URL only; there is no separate IP field.
    expect(screen.queryByPlaceholderText('192.168.1.100 or printer.local')).not.toBeInTheDocument();
    await user.click(submit);

    await waitFor(() => expect(payload).not.toBeNull());
    expect(payload).toMatchObject({
      provider: 'octoprint',
      ip_address: 'octopi.local',
      api_url: 'http://octopi.local',
      auth_token: 'ABCDEF',
    });
  }, 10000);

  it('explains missing OctoPrint permissions', async () => {
    server.use(
      http.post('/api/v1/printers/', () =>
        HttpResponse.json(
          {
            detail: {
              code: 'octoprint_permissions_missing',
              message: 'missing',
              missing_permissions: ['PRINT', 'CONTROL'],
            },
          },
          { status: 400 },
        ),
      ),
    );

    const { user, submit } = await openOctoPrintForm();
    await user.click(submit);

    expect(await screen.findByText(/missing permissions: PRINT, CONTROL/i)).toBeInTheDocument();
  }, 10000);
});
