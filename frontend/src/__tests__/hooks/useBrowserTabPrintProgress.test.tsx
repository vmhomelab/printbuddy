import { afterEach, describe, expect, it } from 'vitest';
import { render, act } from '@testing-library/react';
import { useBrowserTabPrintProgress } from '../../hooks/useBrowserTabPrintProgress';

function Harness() {
  useBrowserTabPrintProgress();
  return null;
}

describe('useBrowserTabPrintProgress', () => {
  afterEach(() => {
    document.title = 'Printbuddy';
  });

  it('shows the live print progress in the browser tab title', () => {
    render(<Harness />);

    act(() => {
      window.dispatchEvent(new CustomEvent('printbuddy-printer-status', {
        detail: {
          printer_id: 1,
          data: { progress: 42, remaining_time: 3600, state: 'printing' },
        },
      }));
    });

    expect(document.title).toBe('42% · Printbuddy');
  });

  it('selects the active print finishing soonest when multiple printers are running', () => {
    render(<Harness />);

    act(() => {
      window.dispatchEvent(new CustomEvent('printbuddy-printer-status', {
        detail: {
          printer_id: 1,
          data: { progress: 80, remaining_time: 7200, state: 'printing' },
        },
      }));
      window.dispatchEvent(new CustomEvent('printbuddy-printer-status', {
        detail: {
          printer_id: 2,
          data: { progress: 35, remaining_time: 900, state: 'printing' },
        },
      }));
    });

    expect(document.title).toBe('35% · Printbuddy');
  });

  it('resets the title when no printer is actively printing', () => {
    document.title = '42% · Printbuddy';
    render(<Harness />);

    act(() => {
      window.dispatchEvent(new CustomEvent('printbuddy-printer-status', {
        detail: {
          printer_id: 1,
          data: { progress: 100, remaining_time: 0, state: 'idle' },
        },
      }));
    });

    expect(document.title).toBe('Printbuddy');
  });
});
