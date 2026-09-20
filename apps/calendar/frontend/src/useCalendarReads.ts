import { connectAppEventSocket, maverickAppIsVisible, observeMaverickVisibility } from '@maverick/pwa-cache';
import { useCallback, useEffect, useRef, useState } from 'react';
import { listCalendars, listConnections, listEvents, readViewFilter } from './api';
import { CALENDAR_UI_STATE_RESOURCE } from './calendar-ui-state';
import { calendarEvents, calendarWindow, readCalendarEvent, readCalendarWindow } from './pwaCache';
import { mergeReloadMode, type ReloadMode } from './runtime';
import type { CalendarConnection, CalendarEvent, CalendarRemoteCalendar, CalendarViewState } from './types';

const foreground = () => maverickAppIsVisible({ requireOnline: false });
const DEFAULT_VIEW: CalendarViewState = { mode: 'default', entity_ids: [], tags: [], conflicts_only: false };

/** Display reads have separate cancellation lanes; accepted mutations live in App. */
export function useCalendarReads(appId: string) {
  const currentAppId = useRef(appId);
  currentAppId.current = appId;
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [connections, setConnections] = useState<CalendarConnection[]>([]);
  const [calendars, setCalendars] = useState<CalendarRemoteCalendar[]>([]);
  const [viewState, setViewState] = useState<CalendarViewState>(DEFAULT_VIEW);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const reads = useRef<{ window?: AbortController; view?: AbortController; detail?: AbortController }>({});
  const reloadTimer = useRef(0);
  const reloadMode = useRef<ReloadMode>('view');
  const interval = useRef(calendarWindow(new Date()));
  const detailId = useRef('');
  const detailEvent = useRef<CalendarEvent | null>(null);

  function begin(lane: keyof typeof reads.current) {
    reads.current[lane]?.abort();
    const controller = new AbortController();
    reads.current[lane] = controller;
    const current = () => !controller.signal.aborted && currentAppId.current === appId && foreground();
    const report = (err: unknown) => {
      if (current() && navigator.onLine !== false) setError(err instanceof Error ? err.message : 'Calendar load failed.');
    };
    return { signal: controller.signal, current, report };
  }

  async function loadView() {
    if (!maverickAppIsVisible()) return;
    const request = begin('view');
    try {
      const value = await readViewFilter(appId, request.signal);
      if (request.current()) setViewState(value);
    } catch (error) { request.report(error); }
  }

  async function loadEvent(id: string) {
    detailId.current = id;
    if (!foreground() || appId !== 'calendar') return;
    const request = begin('detail');
    try {
      await readCalendarEvent(id, request.signal, (item) => {
        if (!request.current()) return;
        detailEvent.current = item;
        setEvents((current) => [...current.filter((event) => event.id !== item.id), item]);
      }, request.report);
    } catch (error) { request.report(error); }
  }

  async function load(options: { viewOnly?: boolean } = {}) {
    if (!foreground()) return;
    if (options.viewOnly) { await loadView(); return; }
    const request = begin('window');
    setIsLoading(true);
    setError('');
    if (detailId.current) void loadEvent(detailId.current);
    let liveCalendars = false;
    if (maverickAppIsVisible()) {
      void loadView();
      void listConnections(appId, request.signal).then((value) => { if (request.current()) setConnections(value); }, request.report);
      void listCalendars(appId, undefined, request.signal).then((value) => {
        if (request.current()) { liveCalendars = true; setCalendars(value); }
      }, request.report);
    }
    try {
      if (appId === 'calendar') {
        await readCalendarWindow(interval.current, request.signal, (model) => {
          if (!request.current()) return;
          const next = calendarEvents(model);
          const detail = detailEvent.current;
          setEvents(detail && detail.id === detailId.current && !next.some((item) => item.id === detail.id) ? [...next, detail] : next);
          if (!liveCalendars) setCalendars(model.calendars);
          setIsLoading(false);
        }, request.report);
      } else if (maverickAppIsVisible()) {
        const next = await listEvents(appId, request.signal);
        if (request.current()) { setEvents(next); setIsLoading(false); }
      }
    } catch (error) {
      request.report(error);
      if (request.current()) setIsLoading(false);
    }
  }

  const latestLoad = useRef(load);
  latestLoad.current = load;
  const handleVisibleDate = useCallback((date: Date) => {
    const next = calendarWindow(date);
    if (next.start_after === interval.current.start_after) return;
    interval.current = next;
    setEvents([]);
    void latestLoad.current();
  }, []);

  useEffect(() => {
    const suspend = () => {
      window.clearTimeout(reloadTimer.current);
      for (const controller of Object.values(reads.current)) controller?.abort();
    };
    let initial = true;
    const stopVisibility = observeMaverickVisibility((visible) => {
      if (!visible) suspend();
      // Online resume comes from the app-events transport once it is live.
      // Offline resume may still paint a previously authorized cached window.
      else if (!initial && navigator.onLine === false) void latestLoad.current();
      initial = false;
    }, { requireOnline: false });
    window.addEventListener('offline', suspend);
    const schedule = (resource?: string) => {
      reloadMode.current = mergeReloadMode(reloadMode.current, resource === 'view-state' ? 'view' : 'full');
      window.clearTimeout(reloadTimer.current);
      if (!maverickAppIsVisible()) return;
      reloadTimer.current = window.setTimeout(() => {
        const mode = reloadMode.current;
        reloadMode.current = 'view';
        void latestLoad.current({ viewOnly: mode === 'view' });
      }, 120);
    };
    const stopEvents = connectAppEventSocket<{ type?: string; owner_app_id?: string; resource?: string }>((payload) => {
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === appId
          && payload.resource !== CALENDAR_UI_STATE_RESOURCE) schedule(payload.resource);
    }, () => schedule());
    return () => { suspend(); stopVisibility(); stopEvents(); window.removeEventListener('offline', suspend); };
  }, [appId]);

  return { events, setEvents, connections, setConnections, calendars, viewState,
    error, setError, isLoading, load, loadEvent, handleVisibleDate };
}
