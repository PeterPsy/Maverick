import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { useCalendarReads } from './useCalendarReads';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CalendarApiError,
  completeGoogleOAuth,
  createEvent,
  deleteEvent,
  listConnections,
  syncCalendar,
  updateEvent,
} from './api';
import { CalendarEventOverlay } from './components/ui/calendar-event-overlay';
import { EventManager, type Event } from './components/ui/event-manager';
import { applyViewState, sortEvents } from './view-state-filtering';
import {
  calendarOAuthCallbackFromLocation,
  eventIdFromParams,
  maverickPlatformOrigin,
  runtimeAppIdFromPathname,
  scalarString,
  type CalendarOAuthCallback,
} from './runtime';


export function App() {
  const runtimeAppIdRef = useRef(runtimeAppIdFromPathname(window.location.pathname));
  const [runtimeAppId, setRuntimeAppId] = useState(runtimeAppIdRef.current);
  const { events, setEvents, connections, setConnections, calendars, viewState, error, setError,
    isLoading, load, loadEvent, handleVisibleDate } = useCalendarReads(runtimeAppId);
  const [focusEventId, setFocusEventId] = useState('');
  const [focusVersion, setFocusVersion] = useState(0);

  function adoptRuntimeAppId(appId: unknown) {
    const nextAppId = scalarString(appId);
    if (!nextAppId || nextAppId === runtimeAppIdRef.current) {
      return;
    }
    runtimeAppIdRef.current = nextAppId;
    setRuntimeAppId(nextAppId);
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
          void loadEvent(eventId);
          setFocusEventId(eventId);
          setFocusVersion((current) => current + 1);
        }
        return;
      }

    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
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
