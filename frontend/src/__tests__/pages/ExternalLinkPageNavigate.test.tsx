/**
 * The framed app may ask Printbuddy to open one of its own pages in place
 * (Printbuddy Orders' "In Printbuddy" link): only from the frame, only from the
 * link's origin, only for a path inside Printbuddy.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes, useLocation } from 'react-router-dom';
import { render } from '../utils';
import { api } from '../../api/client';
import { ExternalLinkPage } from '../../pages/ExternalLinkPage';

const ORIGIN = 'http://orders.local:8090';
const LINK = {
  id: 5,
  name: 'Orders',
  url: `${ORIGIN}/`,
  icon: 'shopping-cart',
  open_in_new_tab: false,
  custom_icon: null,
  sort_order: 0,
  created_at: '2026-09-27T00:00:00Z',
  updated_at: '2026-09-27T00:00:00Z',
};

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

async function renderFrame() {
  window.history.pushState({}, '', '/external/5');
  render(
    <Routes>
      <Route path="/external/:id" element={<ExternalLinkPage />} />
      <Route path="*" element={<Where />} />
    </Routes>,
  );
  return (await screen.findByTitle('Orders')) as HTMLIFrameElement;
}

function ask(frame: HTMLIFrameElement | Window, path: unknown, origin = ORIGIN) {
  const source = frame instanceof HTMLIFrameElement ? frame.contentWindow : frame;
  window.dispatchEvent(new MessageEvent('message', { data: { type: 'printbuddy:navigate', path }, origin, source }));
}

beforeEach(() => {
  vi.spyOn(api, 'getExternalLink').mockResolvedValue(LINK);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ExternalLinkPage navigate requests', () => {
  it('opens the asked-for Printbuddy page', async () => {
    const frame = await renderFrame();
    ask(frame, '/queue?batch=12');
    expect(await screen.findByTestId('where')).toHaveTextContent('/queue?batch=12');
  });

  it.each([
    ['another site', 'https://evil.example/login'],
    ['a protocol-relative address', '//evil.example/login'],
    ['a backslash trick', '/\\evil.example'],
    ['a script', 'javascript:alert(1)'],
    ['a relative path', 'queue'],
    ['no string', 42],
  ])('ignores %s', async (_name, path) => {
    const frame = await renderFrame();
    ask(frame, path);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByTitle('Orders')).toBeInTheDocument();
  });

  it('ignores requests from other windows or origins', async () => {
    const frame = await renderFrame();
    ask(window, '/queue');
    ask(frame, '/queue', 'http://evil.example');
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByTitle('Orders')).toBeInTheDocument();
    expect(screen.queryByTestId('where')).not.toBeInTheDocument();
  });
});
