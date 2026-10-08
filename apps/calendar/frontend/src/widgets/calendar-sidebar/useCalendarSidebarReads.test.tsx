// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { accountSummary } from '../../api';
import { useCalendarSidebarReads } from './useCalendarSidebarReads';

vi.mock('../../api', () => ({ accountSummary: vi.fn(async () => ({ connections: [], calendars: [], localEventCount: 0 })) }));

class Socket {
  static instances: Socket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor() { Socket.instances.push(this); }
  close() { this.onclose?.(); }
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks(); });

it('keeps displayed accounts mounted, aborts reads on close and coalesces refresh on reopen', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', Socket);
  Socket.instances = [];
  let hidden = false;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  const root = createRoot(document.createElement('div'));
  let reads: ReturnType<typeof useCalendarSidebarReads>;
  function Probe() { reads = useCalendarSidebarReads('calendar'); return null; }
  try {
    await act(async () => { root.render(<Probe />); });
    Socket.instances[0].onopen?.();
    expect(reads!.isLoading).toBe(false);
    vi.mocked(accountSummary).mockImplementationOnce((_app, signal) => new Promise((_resolve, reject) => {
      signal?.addEventListener('abort', () => reject(new Error('cancelled by close')));
    }));
    let pending: Promise<void>;
    await act(async () => { pending = reads!.refreshCalendarState(); });
    expect(reads!.isLoading).toBe(false);
    await act(async () => {
      reads!.scheduleRefresh();
      hidden = true;
      document.dispatchEvent(new Event('visibilitychange'));
      await pending;
      vi.advanceTimersByTime(60_000);
    });
    expect(vi.mocked(accountSummary).mock.calls[1][1]?.aborted).toBe(true);
    expect(reads!.error).toBe('');
    expect(accountSummary).toHaveBeenCalledTimes(2);
    await act(async () => {
      hidden = false;
      document.dispatchEvent(new Event('visibilitychange'));
      Socket.instances[1].onopen?.();
      reads!.scheduleRefresh();
      reads!.scheduleRefresh();
      vi.advanceTimersByTime(120);
    });
    expect(accountSummary).toHaveBeenCalledTimes(3);
    expect(reads!.isLoading).toBe(false);
  } finally { act(() => root.unmount()); }
});
