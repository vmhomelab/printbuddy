/**
 * Tests for the SetupPage component.
 */

import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../utils';
import { SetupPage } from '../../pages/SetupPage';

describe('SetupPage', () => {
  it('uses the full Printbuddy app icon in the setup branding', () => {
    render(<SetupPage />);

    const icon = screen.getByAltText('Printbuddy app icon') as HTMLImageElement;
    expect(icon).toBeInTheDocument();
    expect(icon.getAttribute('src')).toContain('/img/printbuddy_icon.png');
    expect(icon).not.toHaveAttribute('src', expect.stringContaining('printbuddy_logo.svg'));
  });
});
