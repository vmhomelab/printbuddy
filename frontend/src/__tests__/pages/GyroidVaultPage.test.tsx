/**
 * Tests for the GyroidVault browse + import page and its settings card.
 */

import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { GyroidVaultPage } from '../../pages/GyroidVaultPage';
import { GyroidVaultSettings } from '../../components/GyroidVaultSettings';

const connected = {
  enabled: true,
  configured: true,
  connected: true,
  version: '2.3.1',
  supported_version: true,
  error: null,
};

const modelList = {
  models: [
    {
      id: 7,
      name: 'Benchy',
      description: 'Boat',
      category_id: 2,
      category_name: 'Tests',
      category_color: null,
      thumbnail_path: '/uploads/thumb-7.png',
      file_count: 2,
      file_types: ['stl', 'document'],
      print_count: 0,
      tags: [],
      updated_at: null,
    },
  ],
  total_items: 1,
  total_pages: 1,
  page: 1,
  limit: 24,
};

const modelDetail = {
  ...modelList.models[0],
  print_tips: '',
  source_url: null,
  web_url: 'http://vault.lan/#/models/7',
  tags: [{ id: 3, name: 'calibration' }],
  files: [
    { id: 70, filename: 'benchy.stl', file_type: 'stl', file_size: 2048, importable: true, imported_library_file_id: null },
    { id: 71, filename: 'readme.pdf', file_type: 'document', file_size: 10, importable: false, imported_library_file_id: null },
    { id: 72, filename: 'hull.3mf', file_type: '3mf', file_size: 10, importable: true, imported_library_file_id: 5 },
  ],
};

function useConnectedHandlers() {
  server.use(
    http.get('*/gyroidvault/status', () => HttpResponse.json(connected)),
    http.get('*/gyroidvault/models', () => HttpResponse.json(modelList)),
    http.get('*/gyroidvault/models/7', () => HttpResponse.json(modelDetail)),
    http.get('*/gyroidvault/categories', () =>
      HttpResponse.json([{ id: 2, name: 'Tests', color: null, model_count: 1 }]),
    ),
    http.get('*/gyroidvault/tags', () => HttpResponse.json([{ id: 3, name: 'calibration' }])),
    http.get('*/gyroidvault/recent-imports', () => HttpResponse.json([])),
    http.get('*/library/folders', () => HttpResponse.json([])),
  );
}

afterEach(() => server.resetHandlers());

describe('GyroidVaultPage', () => {
  it('shows a setup hint when the integration is not configured', async () => {
    server.use(
      http.get('*/gyroidvault/status', () =>
        HttpResponse.json({ ...connected, enabled: false, configured: false, connected: false, version: null }),
      ),
      http.get('*/gyroidvault/recent-imports', () => HttpResponse.json([])),
    );
    render(<GyroidVaultPage />);
    expect(await screen.findByText('GyroidVault is not set up')).toBeInTheDocument();
  });

  it('shows the upstream error when GyroidVault is unreachable', async () => {
    server.use(
      http.get('*/gyroidvault/status', () =>
        HttpResponse.json({ ...connected, connected: false, version: null, error: 'Cannot reach GyroidVault' }),
      ),
      http.get('*/gyroidvault/recent-imports', () => HttpResponse.json([])),
    );
    render(<GyroidVaultPage />);
    expect(await screen.findByText('GyroidVault is not reachable')).toBeInTheDocument();
    expect(screen.getByText(/Cannot reach GyroidVault/)).toBeInTheDocument();
  });

  it('lists models and passes the search to the backend', async () => {
    useConnectedHandlers();
    let lastSearch: string | null = null;
    server.use(
      http.get('*/gyroidvault/models', ({ request }) => {
        lastSearch = new URL(request.url).searchParams.get('search');
        return HttpResponse.json(modelList);
      }),
    );
    render(<GyroidVaultPage />);
    expect(await screen.findByText('Benchy')).toBeInTheDocument();
    const img = screen.getByAltText('Benchy') as HTMLImageElement;
    expect(img.src).toContain('/api/v1/gyroidvault/asset?path=%2Fuploads%2Fthumb-7.png');

    await userEvent.type(screen.getByRole('searchbox'), 'tag:boat');
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(lastSearch).toBe('tag:boat'));
  });

  it('preselects importable, not-yet-imported files and imports them', async () => {
    useConnectedHandlers();
    let importBody: { model_id: number; file_ids: number[]; folder_id: number | null } | null = null;
    server.use(
      http.post('*/gyroidvault/import', async ({ request }) => {
        importBody = (await request.json()) as typeof importBody;
        return HttpResponse.json({
          folder_id: 9,
          files: [{ gyroidvault_file_id: 70, library_file_id: 11, filename: 'benchy.stl', was_existing: false, error: null }],
        });
      }),
    );
    render(<GyroidVaultPage />);
    await userEvent.click(await screen.findByText('Benchy'));

    const stl = (await screen.findByRole('checkbox', { name: 'benchy.stl' })) as HTMLInputElement;
    const pdf = screen.getByRole('checkbox', { name: 'readme.pdf' }) as HTMLInputElement;
    const imported = screen.getByRole('checkbox', { name: 'hull.3mf' }) as HTMLInputElement;
    expect(stl.checked).toBe(true);
    expect(pdf.disabled).toBe(true);
    expect(imported.disabled).toBe(true);
    expect(imported.checked).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: /Import selected \(1\)/ }));
    await waitFor(() => expect(importBody).toEqual({ model_id: 7, file_ids: [70], folder_id: null }));
    expect(await screen.findByRole('link', { name: /View in library/ })).toHaveAttribute('href', '/files?folder=9');
  });
});

describe('GyroidVaultSettings', () => {
  it('never prefills the API key and only sends it when entered', async () => {
    const bodies: Array<Record<string, unknown>> = [];
    server.use(
      http.get('*/gyroidvault/settings', () =>
        HttpResponse.json({ enabled: true, url: 'http://vault.lan', has_api_key: true }),
      ),
      http.put('*/gyroidvault/settings', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        bodies.push(body);
        return HttpResponse.json({ enabled: true, url: String(body.url ?? 'http://vault.lan'), has_api_key: true });
      }),
    );
    render(<GyroidVaultSettings />);
    const keyInput = (await screen.findByLabelText('API key')) as HTMLInputElement;
    expect(keyInput.value).toBe('');
    expect(keyInput.placeholder).toMatch(/Stored/);

    const urlInput = screen.getByLabelText('GyroidVault URL');
    await userEvent.clear(urlInput);
    await userEvent.type(urlInput, 'http://192.168.1.5:3457');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ enabled: true, url: 'http://192.168.1.5:3457' });
  });

  it('shows the connection test result and role warning', async () => {
    server.use(
      http.get('*/gyroidvault/settings', () =>
        HttpResponse.json({ enabled: true, url: 'http://vault.lan', has_api_key: true }),
      ),
      http.post('*/gyroidvault/test', () =>
        HttpResponse.json({
          ok: true,
          version: '2.3.1',
          username: 'admin',
          role: 'admin',
          supported_version: true,
          warning: 'Use a viewer account',
          error: null,
        }),
      ),
    );
    render(<GyroidVaultSettings />);
    await userEvent.click(await screen.findByRole('button', { name: /Test connection/ }));
    const result = await screen.findByTestId('gyroidvault-test-result');
    expect(result).toHaveTextContent('Connected to GyroidVault 2.3.1 as admin (admin)');
    expect(result).toHaveTextContent('Use a viewer account');
  });
});
