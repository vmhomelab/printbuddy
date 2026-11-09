/**
 * Tests for the combined Model import page (MakerWorld, GyroidVault, settings).
 */

import { describe, it, expect, afterEach, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { ModelImportPage } from '../../pages/ModelImportPage';

function useHandlers() {
  server.use(
    http.get('*/makerworld/status', () => HttpResponse.json({ has_cloud_token: true, can_download: true })),
    http.get('*/makerworld/recent-imports', () => HttpResponse.json([])),
    http.get('*/library/folders', () => HttpResponse.json([])),
    http.get('*/gyroidvault/status', () =>
      HttpResponse.json({
        enabled: false,
        configured: false,
        connected: false,
        version: null,
        supported_version: true,
        error: null,
      }),
    ),
    http.get('*/gyroidvault/recent-imports', () => HttpResponse.json([])),
    http.get('*/gyroidvault/settings', () =>
      HttpResponse.json({ enabled: false, url: '', has_api_key: false, report_prints: false }),
    ),
  );
}

beforeEach(() => window.history.replaceState({}, '', '/import'));
afterEach(() => server.resetHandlers());

describe('ModelImportPage', () => {
  it('shows MakerWorld first and offers all three tabs', async () => {
    useHandlers();
    render(<ModelImportPage />);
    expect(await screen.findByRole('heading', { name: 'Model import' })).toBeInTheDocument();
    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs).toEqual(['MakerWorld', 'GyroidVault', 'Settings']);
    expect(screen.getByRole('tab', { name: 'MakerWorld' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByPlaceholderText(/https:\/\/makerworld\.com/i)).toBeInTheDocument();
  });

  it('opens the tab named in ?source= and keeps the URL in sync', async () => {
    useHandlers();
    window.history.replaceState({}, '', '/import?source=gyroidvault');
    render(<ModelImportPage />);
    expect(await screen.findByText('GyroidVault is not set up')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open settings' })).toHaveAttribute('href', '/import?source=settings');

    await userEvent.click(screen.getByRole('tab', { name: 'Settings' }));
    await waitFor(() => expect(window.location.search).toBe('?source=settings'));
  });

  it('groups the GyroidVault connection and the MakerWorld defaults under Settings', async () => {
    useHandlers();
    window.history.replaceState({}, '', '/import?source=settings');
    render(<ModelImportPage />);
    expect(await screen.findByText('GyroidVault model library')).toBeInTheDocument();
    expect(screen.getByText('MakerWorld import defaults')).toBeInTheDocument();
    expect(screen.getByLabelText('Report prints to GyroidVault')).toBeInTheDocument();
  });
});
