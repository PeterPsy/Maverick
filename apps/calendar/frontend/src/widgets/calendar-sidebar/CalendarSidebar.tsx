import { useEffect, useMemo, useState } from 'react';
import { isExactLoopinoParentMessage } from '@loopino/pwa-cache';
import { selectCalendar, syncCalendar } from '../../api';
import { CALENDAR_UI_STATE_RESOURCE, readCalendarUiState } from '../../calendar-ui-state';
import type { CalendarConnection, CalendarRemoteCalendar } from '../../components/ui/calendar-types';
import { t } from '../../preferences';
import { runtimeAppIdFromPathname } from '../../runtime';
import { useCalendarPreferences } from '../../useCalendarPreferences';
import { CalendarAccountItem } from './CalendarAccountItem';
import { buildAccountGroups } from './accounts';
import { useCalendarSidebarReads } from './useCalendarSidebarReads';

export type CalendarOptions = Parameters<typeof selectCalendar>[3];

export function CalendarSidebar() {
  useCalendarPreferences();
  const appId = runtimeAppIdFromPathname(window.location.pathname);
  const { events, localEventCount, connections, calendars, setCalendars, isLoading, error, setError,
    refreshCalendarState, scheduleRefresh } = useCalendarSidebarReads(appId);
  const [uiState, setUiState] = useState(() => readCalendarUiState(appId));
  const [activeOperation, setActiveOperation] = useState('');
  const accountGroups = useMemo(
    () => buildAccountGroups(events, connections, calendars, localEventCount),
    [events, connections, calendars, localEventCount],
  );

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (!isExactLoopinoParentMessage(event) || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.owner_app_id !== appId && payload.type !== 'loopino.widget.context-changed') return;
      if (payload.type === 'loopino.widget.context-changed' || payload.resource === CALENDAR_UI_STATE_RESOURCE) {
        setUiState(readCalendarUiState(appId));
      }
      if (payload.type === 'loopino.widget.context-changed'
          || payload.type === 'loopino.widget.data-changed' && payload.resource !== CALENDAR_UI_STATE_RESOURCE) {
        scheduleRefresh();
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId, scheduleRefresh]);

  function notify(resource: string) {
    window.parent?.postMessage({ type: 'loopino.app.data-changed', owner_app_id: appId, resource }, '*');
  }

  async function updateCalendar(calendar: CalendarRemoteCalendar, options: CalendarOptions) {
    setActiveOperation(`calendar:${calendar.connection_id}:${calendar.id}`);
    setError('');
    try {
      const updated = await selectCalendar(appId, calendar.connection_id, calendar.provider_calendar_id, options);
      setCalendars((current) => current.map((item) =>
        item.connection_id === updated.connection_id && item.provider_calendar_id === updated.provider_calendar_id ? updated : item));
      notify('calendars');
    } catch (error) {
      setError(error instanceof Error ? error.message : t('Calendar setting could not be saved.'));
    } finally {
      setActiveOperation('');
    }
  }

  async function syncConnection(connection: CalendarConnection) {
    if (!connection.id) return;
    setActiveOperation(connection.id);
    setError('');
    try {
      const result = await syncCalendar(appId, connection.id);
      await refreshCalendarState();
      if (!result.synced) setError(t('Sync is partial; continue syncing to fetch remaining pages.'));
      notify('events');
    } catch (error) {
      setError(error instanceof Error ? error.message : t('Calendar sync failed.'));
    } finally {
      setActiveOperation('');
    }
  }

  return (
    <main className="calendar-sidebar-widget">
      <div className="calendar-sidebar-list">
        {error && <p className="calendar-sidebar-error" role="alert">{error}</p>}
        {isLoading ? <AccountSkeleton /> : accountGroups.map((account) => (
          <CalendarAccountItem
            account={account}
            busy={Boolean(activeOperation)}
            filtered={uiState.selectedAccounts.includes(account.id)}
            key={account.id}
            onSync={syncConnection}
            onUpdate={updateCalendar}
            syncing={activeOperation === account.id}
          />
        ))}
      </div>
    </main>
  );
}

function AccountSkeleton() {
  return (
    <div className="calendar-sidebar-skeleton" role="status" aria-label={t('Calendar accounts are loading')}>
      {Array.from({ length: 5 }, (_, index) => (
        <div className="calendar-sidebar-skeleton-row" key={index} aria-hidden="true"><span /><span /></div>
      ))}
    </div>
  );
}
