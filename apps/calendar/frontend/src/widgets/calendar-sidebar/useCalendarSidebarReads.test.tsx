// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { listCalendars, listConnections, listEvents } from '../../api';
import { useCalendarSidebarReads } from './useCalendarSidebarReads';

vi.mock('../../api', () => ({ listEvents: vi.fn(async () => []), listConnections: vi.fn(async () => []), listCalendars: vi.fn(async () => []) }));

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
    vi.mocked(listEvents).mockImplementationOnce((_app, signal) => new Promise((_resolve, reject) => {
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
    expect(vi.mocked(listEvents).mock.calls[1][1]?.aborted).toBe(true);
    expect(vi.mocked(listConnections).mock.calls[1][1]?.aborted).toBe(true);
    expect(vi.mocked(listCalendars).mock.calls[1][2]?.aborted).toBe(true);
    expect(reads!.error).toBe('');
    expect(listEvents).toHaveBeenCalledTimes(2);
    await act(async () => {
      hidden = false;
      document.dispatchEvent(new Event('visibilitychange'));
      Socket.instances[1].onopen?.();
      reads!.scheduleRefresh();
      reads!.scheduleRefresh();
      vi.advanceTimersByTime(120);
    });
    expect(listEvents).toHaveBeenCalledTimes(3);
    expect(reads!.isLoading).toBe(false);
  } finally { act(() => root.unmount()); }
});
