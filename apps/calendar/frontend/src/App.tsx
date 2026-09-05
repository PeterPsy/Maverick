import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { calendarEvents, calendarWindow, readCalendarWindow, readCalendarEvent } from './pwaCache';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CalendarApiError,
  completeGoogleOAuth,
  createEvent,
  deleteEvent,
  listCalendars,
  listConnections,
  listEvents,
  readViewFilter,
  syncCalendar,
  updateEvent,
} from './api';
import { CALENDAR_UI_STATE_RESOURCE } from './calendar-ui-state';
import { CalendarEventOverlay } from './components/ui/calendar-event-overlay';
import { EventManager, type Event } from './components/ui/event-manager';
import { applyViewState, sortEvents } from './view-state-filtering';
import {
  calendarOAuthCallbackFromLocation,
  eventIdFromParams,
  mergeReloadMode,
  maverickPlatformOrigin,
  runtimeAppIdFromPathname,
  scalarString,
  type CalendarOAuthCallback,
  type ReloadMode,
} from './runtime';
import type { CalendarConnection, CalendarRemoteCalendar, CalendarViewState } from './types';

const APP_EVENTS_WS_PATH = '/api/apps/events/ws';
const DEFAULT_VIEW_STATE: CalendarViewState = { mode: 'default', entity_ids: [], tags: [], conflicts_only: false };

export function App() {
  const runtimeAppIdRef = useRef(runtimeAppIdFromPathname(window.location.pathname));
  const [runtimeAppId, setRuntimeAppId] = useState(runtimeAppIdRef.current);
  const [events, setEvents] = useState<Event[]>([]);
  const [connections, setConnections] = useState<CalendarConnection[]>([]);
  const [calendars, setCalendars] = useState<CalendarRemoteCalendar[]>([]);
  const [viewState, setViewState] = useState<CalendarViewState>(DEFAULT_VIEW_STATE);
  const [error, setError] = useState('');
  const [focusEventId, setFocusEventId] = useState('');
  const [focusVersion, setFocusVersion] = useState(0);
  const reloadTimer = useRef(0);
  const readController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const interval = useRef(calendarWindow(new Date()));
  const [isLoading, setIsLoading] = useState(true);
  const handleVisibleDate = useCallback((date: Date) => {
    const next = calendarWindow(date);
    if (next.start_after === interval.current.start_after) return;
    interval.current = next;
    setEvents([]);
    void load();
  }, []);
  const pendingReloadMode = useRef<ReloadMode>('view');

  function adoptRuntimeAppId(appId: unknown) {
    const nextAppId = scalarString(appId);
    if (!nextAppId || nextAppId === runtimeAppIdRef.current) {
      return;
    }
    runtimeAppIdRef.current = nextAppId;
    setRuntimeAppId(nextAppId);
  }

  async function load(options: { viewOnly?: boolean } = {}) {
    const appId = runtimeAppIdRef.current;
    setError('');
    try {
      if (options.viewOnly) {
        setViewState(await readViewFilter(appId));
        return;
      }
      readController.current?.abort();
      const controller = new AbortController();
      readController.current = controller;
      setIsLoading(true);
      const current = () => !controller.signal.aborted && appId === runtimeAppIdRef.current;
      const reportError = (err: unknown) => { if (current()) setError(err instanceof Error ? err.message : 'Calendar load failed.'); };
      // Display reads must not wait for provider connections or UI preferences.
      void readViewFilter(appId).then((value) => { if (current()) setViewState(value); }, reportError);
      void listConnections(appId).then((value) => { if (current()) setConnections(value); }, reportError);
      if (appId === 'calendar') {
        await readCalendarWindow(interval.current, controller.signal, (model) => {
          if (!current()) return;
          setEvents(calendarEvents(model));
          setCalendars(model.calendars);
          setIsLoading(false);
        }, reportError);
      } else {
        const nextEvents = await listEvents(appId);
        if (current()) { setEvents(nextEvents); setIsLoading(false); }
        void listCalendars(appId).then((value) => { if (current()) setCalendars(value); }, reportError);
      }
    } catch (err) {
      if (!(err instanceof Error && err.name === 'AbortError')) { setError(err instanceof Error ? err.message : 'Calendar load failed.'); setIsLoading(false); }
    }
  }

  function scheduleReload(resource?: string) {
    const requestedMode: ReloadMode = resource === 'view-state' ? 'view' : 'full';
    pendingReloadMode.current = mergeReloadMode(pendingReloadMode.current, requestedMode);
    window.clearTimeout(reloadTimer.current);
    reloadTimer.current = window.setTimeout(() => {
      const mode = pendingReloadMode.current;
      pendingReloadMode.current = 'view';
      void load({ viewOnly: mode === 'view' });
    }, 120);
  }

  useEffect(() => {
    const oauthCallback = calendarOAuthCallbackFromLocation(
      window.location.pathname,
      window.location.search,
      maverickPlatformOrigin(),
    );
    if (oauthCallback) {
      adoptRuntimeAppId(oauthCallback.appId);
      void handleOAuthCallback(oauthCallback);
    } else {
      void load();
    }
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: runtimeAppIdRef.current }, "*");
    return () => { window.clearTimeout(reloadTimer.current); readController.current?.abort(); detailController.current?.abort(); };
  }, []);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (!isExactMaverickParentMessage(event) || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: Record<string, unknown>;
        resource?: string;
        type?: string;
      };
      if (payload.type === 'maverick.app.navigate') {
        if (payload.app_id && payload.app_id !== runtimeAppIdRef.current) {
          return;
        }
        adoptRuntimeAppId(payload.app_id);
        const eventId = eventIdFromParams(payload.params || {});
        if (eventId) {
          if (runtimeAppIdRef.current === 'calendar') {
            detailController.current?.abort();
            const controller = new AbortController();
            detailController.current = controller;
            const report = (error: unknown) => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Calendar detail failed.'); };
            void readCalendarEvent(eventId, controller.signal, (item) => setEvents((current) => [...current.filter((event) => event.id !== item.id), item]), report).catch(report);
          }
          setFocusEventId(eventId);
          setFocusVersion((current) => current + 1);
        }
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === runtimeAppIdRef.current) {
        if (payload.resource === CALENDAR_UI_STATE_RESOURCE) {
          return;
        }
        scheduleReload(payload.resource);
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  useEffect(() => {
    if (typeof WebSocket === 'undefined') {
      return undefined;
    }
    let closed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer = 0;
    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${window.location.host}${APP_EVENTS_WS_PATH}`);
      socket.onmessage = (message) => {
        try {
          const payload = JSON.parse(message.data) as { type?: string; owner_app_id?: string };
          if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === runtimeAppIdRef.current) {
            const resource = (payload as { resource?: string }).resource;
            if (resource !== CALENDAR_UI_STATE_RESOURCE) {
              scheduleReload(resource);
            }
          }
        } catch {
          return;
        }
      };
      socket.onclose = () => {
        if (!closed) {
          reconnectTimer = window.setTimeout(connect, 1000);
        }
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  async function handleCreate(event: Omit<Event, 'id'>) {
    setError('');
    try {
      const created = await createEvent(runtimeAppId, event);
      setEvents((current) => sortEvents([...current.filter((item) => item.id !== created.id), created]));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Calendar create failed.';
      setError(message);
      throw err;
    }
  }

  async function handleUpdate(id: string, event: Partial<Event>) {
    setError('');
    try {
      const updated = await updateEvent(runtimeAppId, id, event);
      setEvents((current) => sortEvents(current.map((item) => (item.id === id ? updated : item))));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Calendar update failed.';
      setError(message);
      throw err;
    }
  }

  async function handleDelete(id: string, event?: Event) {
    setError('');
    try {
      await deleteEvent(runtimeAppId, id, event?.revision, event);
      setEvents((current) => current.filter((event) => event.id !== id));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Calendar delete failed.';
      setError(message);
      throw err;
    }
  }

  async function createOverlayEvent(event: Omit<Event, 'id'>) {
    setError('');
    try {
      const created = await createEvent(runtimeAppIdRef.current, event);
      setEvents((current) => sortEvents([...current.filter((item) => item.id !== created.id), created]));
      notifyCalendarDataChanged(runtimeAppIdRef.current);
      return created;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Calendar create failed.';
      setError(message);
      throw err;
    }
  }

  async function updateOverlayEvent(id: string, event: Partial<Event>) {
    setError('');
    try {
      const updated = await updateEvent(runtimeAppIdRef.current, id, event);
      setEvents((current) => sortEvents(current.map((item) => (item.id === id ? updated : item))));
      notifyCalendarDataChanged(runtimeAppIdRef.current);
      return updated;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Calendar update failed.';
      setError(message);
      throw err;
    }
  }

  async function deleteOverlayEvent(event: Event) {
    setError('');
    try {
      await deleteEvent(runtimeAppIdRef.current, event.id, event.revision, event);
      setEvents((current) => current.filter((item) => item.id !== event.id));
      notifyCalendarDataChanged(runtimeAppIdRef.current);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Calendar delete failed.';
      setError(message);
      throw err;
    }
  }

  async function handleOAuthCallback(callback: CalendarOAuthCallback) {
    const appId = callback.appId || runtimeAppIdRef.current;
    setError('');
    if (callback.error) {
      await load();
      setError(`Google Calendar authorization failed: ${callback.error}.`);
      return;
    }
    if (!callback.code || !callback.state) {
      await load();
      setError('Google Calendar authorization callback is missing code or state. Start the connection again.');
      return;
    }
    try {
      const completed = await completeGoogleOAuth(appId, {
        code: callback.code,
        state: callback.state,
        redirectUri: callback.redirectUri,
      });
      setConnections(await listConnections(appId));
      await syncCalendar(appId, completed.connection.id);
      await load();
      window.history.replaceState({}, '', `/apps/${encodeURIComponent(appId)}/`);
    } catch (err) {
      const message = operationalErrorMessage(err, 'Google Calendar connection failed.');
      await load();
      setError(message);
    }
  }

  function handleEventOpen(event: Event) {
    window.parent?.postMessage(
      {
        type: 'maverick.app.open-app',
        app_id: runtimeAppId,
        params: {
          app_page: `events/${event.id}`,
          event_id: event.id
        }
      },
      "*"
    );
  }

  const visibleEvents = useMemo(() => applyViewState(events, viewState, focusEventId), [events, viewState, focusEventId]);

  return (
    <main className="calendar-app relative">
      {error ? <div className="calendar-error">{error}</div> : null}
      {isLoading && events.length === 0 ? <div role="status">Loading calendar…</div> : null}
      <EventManager
        onVisibleDateChange={handleVisibleDate}
        className="calendar-board"
        events={visibleEvents}
        onEventCreate={handleCreate}
        onEventUpdate={handleUpdate}
        onEventDelete={handleDelete}
        categories={['Meeting', 'Task', 'Reminder', 'Personal']}
        availableTags={['Important', 'Urgent', 'Work', 'Personal', 'Team', 'Client']}
        defaultView="month"
        focusEventId={focusEventId}
        focusVersion={focusVersion}
        viewState={viewState}
        onEventOpen={handleEventOpen}
        runtimeAppId={runtimeAppId}
        calendarConnections={connections}
        calendars={calendars}
      />
      <CalendarEventOverlay
        runtimeAppId={runtimeAppId}
        events={events}
        connections={connections}
        calendars={calendars}
        categories={['Meeting', 'Task', 'Reminder', 'Personal']}
        availableTags={['Important', 'Urgent', 'Work', 'Personal', 'Team', 'Client']}
        onCreateEvent={createOverlayEvent}
        onUpdateEvent={updateOverlayEvent}
        onDeleteEvent={deleteOverlayEvent}
      />
    </main>
  );
}

function notifyCalendarDataChanged(appId: string) {
  window.parent?.postMessage({ type: 'maverick.app.data-changed', owner_app_id: appId, resource: 'events' }, "*");
}

function operationalErrorMessage(error: unknown, fallback: string) {
  if (error instanceof CalendarApiError && error.code === 'missing_secret_grant') {
    const detail = error.detail.toLowerCase();
    if (detail.includes('refresh token')) {
      return 'Calendar cannot access the resource-scoped Google Calendar refresh token. In Vault/Core Secrets, grant Calendar access to `google-calendar-refresh-token` for this calendar_connection, then retry.';
    }
    return 'Calendar cannot access Google OAuth credentials. In Vault/Core Secrets, grant Calendar access to `google-oauth-client-id` and `google-oauth-client-secret`, then retry.';
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}
