// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { usePendingDeletion } from './usePendingDeletion';
import type { CalendarEvent } from './types';
const event: CalendarEvent = { id: 'e', title: 'Event', color: 'blue', startTime: new Date(), endTime: new Date(Date.now() + 3600000), revision: 1 };
afterEach(() => vi.useRealTimers());
it('allows undo before contacting the provider and commits after the delay', async () => {
  vi.useFakeTimers();
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div'); const root = createRoot(host), remove = vi.fn(async () => {});
  let pending: ReturnType<typeof usePendingDeletion>;
  function Harness() { pending = usePendingDeletion(remove); return pending!.notice; }
  try {
    await act(async () => root.render(<Harness />));
    act(() => pending!.schedule(event));
    expect(remove).not.toHaveBeenCalled();
    act(() => host.querySelector<HTMLButtonElement>('button')!.click());
    await act(async () => vi.advanceTimersByTimeAsync(9000));
    expect(remove).not.toHaveBeenCalled();
    act(() => pending!.schedule(event));
    await act(async () => vi.advanceTimersByTimeAsync(9000));
    expect(remove).toHaveBeenCalledExactlyOnceWith(event);
  } finally { act(() => root.unmount()); }
});
