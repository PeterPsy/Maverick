import { useEffect, useMemo, useRef, useState } from 'react';
import { createEvent, deleteEvent, listEvents, readViewFilter, updateEvent } from './api';
import { EventManager, type Event } from './components/ui/event-manager';
import { applyViewState, sortEvents } from './view-state-filtering';
import { eventIdFromParams, mergeReloadMode, runtimeAppIdFromPathname, scalarString, type ReloadMode } from './runtime';
import type { CalendarViewState } from './types';

const APP_EVENTS_WS_PATH = '/api/apps/events/ws';
const DEFAULT_VIEW_STATE: CalendarViewState = { mode: 'default', entity_ids: [], tags: [], conflicts_only: false };

export function App() {
  const runtimeAppIdRef = useRef(runtimeAppIdFromPathname(window.location.pathname));
  const [runtimeAppId, setRuntimeAppId] = useState(runtimeAppIdRef.current);
  const [events, setEvents] = useState<Event[]>([]);
  const [viewState, setViewState] = useState<CalendarViewState>(DEFAULT_VIEW_STATE);
  const [error, setError] = useState('');
  const [focusEventId, setFocusEventId] = useState('');
  const [focusVersion, setFocusVersion] = useState(0);
  const reloadTimer = useRef(0);
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
      const [nextEvents, nextViewState] = await Promise.all([listEvents(appId), readViewFilter(appId)]);
      setEvents(nextEvents);
      setViewState(nextViewState);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Calendar load failed.');
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
    void load();
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: runtimeAppIdRef.current }, window.location.origin);
    return () => window.clearTimeout(reloadTimer.current);
  }, []);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
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
          setFocusEventId(eventId);
          setFocusVersion((current) => current + 1);
        }
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === runtimeAppIdRef.current) {
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
            scheduleReload((payload as { resource?: string }).resource);
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
      await deleteEvent(runtimeAppId, id, event?.revision);
      setEvents((current) => current.filter((event) => event.id !== id));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Calendar delete failed.';
      setError(message);
      throw err;
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
      window.location.origin
    );
  }

  const visibleEvents = useMemo(() => applyViewState(events, viewState, focusEventId), [events, viewState, focusEventId]);

  return (
    <main className="calendar-app">
      {error ? <div className="calendar-error">{error}</div> : null}
      <EventManager
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
      />
    </main>
  );
}
