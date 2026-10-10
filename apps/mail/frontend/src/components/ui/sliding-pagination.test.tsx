// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import SlidingPagination from './sliding-pagination';

it('keeps adjacent pages reachable at the beginning, middle and end of a large collection', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const change = vi.fn();
  try {
    for (const [current, adjacent] of [[1, 2], [20, 21], [40, 39]]) {
      await act(async () => root.render(<SlidingPagination totalPages={40} currentPage={current} onPageChange={change} maxVisiblePages={7} />));
      const buttons = [...container.querySelectorAll<HTMLButtonElement>('button')];
      expect(buttons.map((button) => button.textContent)).toContain(String(current));
      const target = buttons.find((button) => button.textContent === String(adjacent));
      expect(target).toBeDefined();
      await act(async () => target!.click());
      expect(change).toHaveBeenLastCalledWith(adjacent);
      expect(buttons.length).toBeLessThanOrEqual(5);
    }
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});
