import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useCommitted } from '../../hooks/useCommitted';

describe('useCommitted', () => {
  it('is false while rendering and true once committed', () => {
    const seen: boolean[] = [];
    const { result } = renderHook(() => {
      const committed = useCommitted();
      seen.push(committed);
      return committed;
    });
    // The render React may still throw away sees false: no stream src yet.
    expect(seen[0]).toBe(false);
    expect(result.current).toBe(true);
  });

  it('stays true on later renders', () => {
    const { result, rerender } = renderHook(() => useCommitted());
    rerender();
    expect(result.current).toBe(true);
  });
});
