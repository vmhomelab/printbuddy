import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ThemeProvider, useTheme } from '../../contexts/ThemeContext';

function ThemeProbe() {
  const theme = useTheme();
  return (
    <div
      data-testid="theme-probe"
      data-mode={theme.mode}
      data-dark-accent={theme.darkAccent}
      data-light-accent={theme.lightAccent}
    />
  );
}

describe('ThemeProvider defaults', () => {
  beforeEach(() => {
    vi.mocked(localStorage.getItem).mockReturnValue(null);
    vi.mocked(localStorage.setItem).mockClear();
    vi.mocked(localStorage.removeItem).mockClear();
    document.documentElement.className = '';
  });

  it('starts new browser installs in dark mode with turquoise accents', () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );

    const probe = screen.getByTestId('theme-probe');
    expect(probe).toHaveAttribute('data-mode', 'dark');
    expect(probe).toHaveAttribute('data-dark-accent', 'teal');
    expect(probe).toHaveAttribute('data-light-accent', 'teal');
    expect(document.documentElement).toHaveClass('dark');
    expect(document.documentElement).toHaveClass('accent-teal');
  });
});
