// @vitest-environment happy-dom
import { act, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { usePreviewDialogFocus } from './usePreviewDialogFocus';

afterEach(() => vi.restoreAllMocks());

it('focuses Close, wraps keyboard focus, skips hidden actions and restores the opener', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(function (this: HTMLElement) {
    return (this.hidden ? [] : [{}]) as unknown as DOMRectList;
  });
  const opener = document.createElement('button');
  const container = document.createElement('div');
  document.body.append(opener, container);
  opener.focus();
  const root = createRoot(container);
  function Harness({ open }: { open: boolean }) {
    const ref = useRef<HTMLElement>(null);
    usePreviewDialogFocus(open, ref);
    return open ? <section ref={ref}>
      <button hidden>Hidden fullscreen</button><button>Download</button>
      <button disabled>Unavailable</button><button aria-label="Close preview">Close</button>
    </section> : null;
  }
  try {
    await act(async () => root.render(<Harness open />));
    const controls = container.querySelectorAll('button');
    expect(document.activeElement).toBe(controls[3]);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(controls[1]);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }));
    expect(document.activeElement).toBe(controls[3]);
    await act(async () => root.render(<Harness open={false} />));
    expect(document.activeElement).toBe(opener);
  } finally {
    await act(async () => root.unmount());
    opener.remove(); container.remove();
  }
});
