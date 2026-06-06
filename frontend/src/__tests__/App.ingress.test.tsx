/**
 * Regression coverage for Home Assistant Ingress path-prefix routing.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from '../App';

describe('App Home Assistant ingress routing', () => {
  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('renders the standalone camera route when the URL is prefixed by Home Assistant ingress', async () => {
    window.history.replaceState({}, '', '/api/hassio_ingress/printbuddy123/camera/1');

    render(<App />);

    await waitFor(() => {
      expect(screen.getByAltText('Camera stream')).toBeInTheDocument();
    });

    const src = screen.getByAltText('Camera stream').getAttribute('src') || '';
    expect(src).toContain('/api/hassio_ingress/printbuddy123/api/v1/printers/1/camera/stream');
  });
});
