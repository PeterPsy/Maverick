// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { readCalendarWindow } from './pwaCache';
import { listConnections, readViewFilter } from './api';

vi.mock('./api', () => ({
  readViewFilter: vi.fn(async () => ({ mode: 'default', entity_ids: [], tags: [], conflicts_only: false })),
  listConnections: vi.fn(async () => []),
  listCalendars: vi.fn(async () => []),
}));
vi.mock('./pwaCache', async (original) => ({ ...await original<object>(), readCalendarWindow: vi.fn() }));
vi.mock('./components/ui/event-manager', () => ({ EventManager: ({ events }: { events: Array<{ title: string }> }) => <div>{events.map((event) => event.title).join(',')}</div> }));
vi.mock('./components/ui/calendar-event-overlay', () => ({ CalendarEventOverlay: () => null }));

class Socket {
  static instances: Socket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  constructor() { Socket.instances.push(this); }
  close() { this.onclose?.(); }
}

describe('Calendar event recovery', () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks(); });
  it('rereads changed data after reconnection, coalesces events, and cancels on unmount', async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    vi.spyOn(Math, 'random').mockReturnValue(.5);
    vi.stubGlobal('WebSocket', Socket);
    Socket.instances = [];
    const host = document.createElement('div');
    const root = createRoot(host);
    let title = 'Before disconnect';
    vi.mocked(readCalendarWindow).mockImplementation(async (_window, _signal, update) => {
      update({ events: [{ id: 'event', title, startTime: '2026-09-05T10:00:00Z', endTime: '2026-09-05T11:00:00Z', color: 'blue' }], calendars: [], has_more: false });
    });
    try {
      await act(async () => { root.render(<App />); });
      Socket.instances[0].onopen?.();
      expect(readCalendarWindow).toHaveBeenCalledOnce();
      expect(host.textContent).toContain('Before disconnect');
      Socket.instances[0].close();
      title = 'Changed elsewhere';
      await act(async () => { vi.advanceTimersByTime(1_000); });
      expect(readCalendarWindow).toHaveBeenCalledOnce();
      await act(async () => {
        Socket.instances[1].onopen?.();
        Socket.instances[1].onmessage?.({ data: JSON.stringify({ type: 'maverick.app.data-changed', owner_app_id: 'calendar', resource: 'events' }) });
        vi.advanceTimersByTime(120);
      });
      expect(readCalendarWindow).toHaveBeenCalledTimes(2);
      expect(host.textContent).toContain('Changed elsewhere');
      Socket.instances[1].close();
    } finally { act(() => root.unmount()); }
    vi.advanceTimersByTime(60_000);
    expect(Socket.instances).toHaveLength(2);
    expect(readCalendarWindow).toHaveBeenCalledTimes(2);
  });

  it('aborts every read and pending refresh when hidden, ignores late results and resumes once', async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', Socket);
    Socket.instances = [];
    let hidden = false;
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
    const host = document.createElement('div');
    const root = createRoot(host);
    let late: Parameters<typeof readCalendarWindow>[2];
    let signal: AbortSignal;
    vi.mocked(readCalendarWindow).mockImplementationOnce(async (_window, currentSignal, update) => {
      signal = currentSignal;
      late = update;
      await new Promise<void>((_resolve, reject) => currentSignal.addEventListener('abort', () => reject(new Error('Retry operation was cancelled.'))));
    }).mockImplementation(async (_window, _signal, update) => {
      update({ events: [], calendars: [], has_more: false });
    });
    try {
      await act(async () => { root.render(<App />); });
      Socket.instances[0].onopen?.();
      await act(async () => {
        Socket.instances[0].onmessage?.({ data: JSON.stringify({ type: 'maverick.app.data-changed', owner_app_id: 'calendar', resource: 'events' }) });
        hidden = true;
        document.dispatchEvent(new Event('visibilitychange'));
      });
      expect(signal!.aborted).toBe(true);
      expect(vi.mocked(listConnections).mock.calls[0][1]?.aborted).toBe(true);
      expect(vi.mocked(readViewFilter).mock.calls[0][1]?.aborted).toBe(true);
      await act(async () => {
        late!({ events: [{ id: 'late', title: 'Late hidden event', startTime: '', endTime: '', color: 'blue' }], calendars: [], has_more: false });
        vi.advanceTimersByTime(60_000);
      });
      expect(host.textContent).not.toContain('Late hidden event');
      expect(host.textContent).not.toContain('cancelled');
      expect(readCalendarWindow).toHaveBeenCalledOnce();
      expect(Socket.instances).toHaveLength(1);
      await act(async () => {
        hidden = false;
        document.dispatchEvent(new Event('visibilitychange'));
        Socket.instances[1].onopen?.();
        vi.advanceTimersByTime(120);
      });
      expect(readCalendarWindow).toHaveBeenCalledTimes(2);
      expect(host.textContent).not.toContain('cancelled');
    } finally { act(() => root.unmount()); }
  });

  it('paints the cached window offline without requesting network-only metadata', async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal('navigator', { onLine: false });
    vi.stubGlobal('WebSocket', Socket);
    Socket.instances = [];
    const host = document.createElement('div');
    const root = createRoot(host);
    vi.mocked(readCalendarWindow).mockImplementation(async (_window, _signal, update) => {
      update({ events: [{ id: 'cached', title: 'Cached appointment', startTime: '', endTime: '', color: 'blue' }], calendars: [], has_more: false });
    });
    try {
      await act(async () => { root.render(<App />); });
      expect(host.textContent).toContain('Cached appointment');
      expect(listConnections).not.toHaveBeenCalled();
      expect(readViewFilter).not.toHaveBeenCalled();
      expect(Socket.instances).toHaveLength(0);
    } finally { act(() => root.unmount()); }
  });
});
