import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { notifyCalendarUiStateChanged, writeCalendarUiState } from '../../calendar-ui-state';
import { runtimeAppIdFromPathname } from '../../runtime';
import './styles.css';

const PRIMARY_ACTION_LABEL = 'New event';
const WIDGET_ID = 'calendar-sidebar-footer';

function CalendarSidebarFooterWidget() {
  const appId = runtimeAppIdFromPathname(window.location.pathname);

  useEffect(() => {
    postPrimaryActionState(appId);

    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; type?: string; widget_id?: string };
      if (payload.owner_app_id !== appId || payload.widget_id !== WIDGET_ID) {
        return;
      }
      if (payload.type === 'maverick.widget.primary-action.query') {
        postPrimaryActionState(appId);
      }
      if (payload.type === 'maverick.widget.primary-action.invoke') {
        openCreate(appId);
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  return (
    <main className="calendar-sidebar-footer-widget">
      <button className="calendar-sidebar-footer__new-event" onClick={() => openCreate(appId)} type="button">
        <span aria-hidden="true" className="calendar-sidebar-footer__plus" />
        <span>New event</span>
      </button>
    </main>
  );
}

function openCreate(appId: string) {
  writeCalendarUiState(appId, { sidebarMode: 'create', selectedEventId: '' });
  notifyCalendarUiStateChanged(appId, { action: 'new-event' });
}

function postPrimaryActionState(appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.primary-action.state',
      owner_app_id: appId,
      widget_id: WIDGET_ID,
      available: true,
      label: PRIMARY_ACTION_LABEL,
      preferred_surface: 'sidebar',
    },
    window.location.origin,
  );
}

createRoot(document.getElementById('calendar-sidebar-footer-root') as HTMLElement).render(<CalendarSidebarFooterWidget />);
