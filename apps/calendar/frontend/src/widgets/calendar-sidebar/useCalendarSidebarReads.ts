import { connectAppEventSocket, maverickAppIsVisible, observeMaverickVisibility } from '@maverick/pwa-cache';
import { useCallback, useEffect, useRef, useState } from 'react';
import { listCalendars, listConnections, listEvents } from '../../api';
import { CALENDAR_UI_STATE_RESOURCE } from '../../calendar-ui-state';
import type { CalendarConnection, CalendarEvent, CalendarRemoteCalendar } from '../../types';

export function useCalendarSidebarReads(appId: string) {
  const currentAppId = useRef(appId);
  currentAppId.current = appId;
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [connections, setConnections] = useState<CalendarConnection[]>([]);
  const [calendars, setCalendars] = useState<CalendarRemoteCalendar[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const read = useRef<AbortController | null>(null);
  const timer = useRef(0);

  const refreshCalendarState = useCallback(async () => {
    if (!maverickAppIsVisible()) return;
    read.current?.abort();
    const controller = new AbortController();
    read.current = controller;
    const current = () => !controller.signal.aborted && currentAppId.current === appId;
    try {
      const [nextEvents, nextConnections, nextCalendars] = await Promise.all([
        listEvents(appId, controller.signal), listConnections(appId, controller.signal),
        listCalendars(appId, undefined, controller.signal),
      ]);
      if (!current()) return;
      setEvents(nextEvents); setConnections(nextConnections); setCalendars(nextCalendars); setError('');
    } catch (error) {
      if (current()) setError(error instanceof Error ? error.message : 'Unable to load Calendar accounts.');
    } finally {
      if (current()) setIsLoading(false);
    }
  }, [appId]);

  const scheduleRefresh = useCallback(() => {
    window.clearTimeout(timer.current);
    if (maverickAppIsVisible()) timer.current = window.setTimeout(() => { void refreshCalendarState(); }, 120);
  }, [refreshCalendarState]);

  useEffect(() => {
    const suspend = () => { window.clearTimeout(timer.current); read.current?.abort(); };
    let initial = true;
    const stopVisibility = observeMaverickVisibility((visible) => {
      if (!visible) suspend();
      else if (initial) void refreshCalendarState();
      initial = false;
    });
    const stopEvents = connectAppEventSocket<{ type?: string; owner_app_id?: string; resource?: string }>((event) => {
      if (event.type === 'maverick.app.data-changed' && event.owner_app_id === appId
          && event.resource !== CALENDAR_UI_STATE_RESOURCE) scheduleRefresh();
    }, scheduleRefresh);
    return () => { suspend(); stopVisibility(); stopEvents(); };
  }, [appId, refreshCalendarState, scheduleRefresh]);

  return { events, connections, calendars, setCalendars, isLoading, error, setError, refreshCalendarState, scheduleRefresh };
}
