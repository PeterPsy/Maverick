import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CalendarPlus, Plus } from 'lucide-react';
import { startGoogleOAuth } from '../../api';
import { notifyCalendarUiStateChanged, writeCalendarUiState } from '../../calendar-ui-state';
import { calendarOAuthRedirectUri, runtimeAppIdFromPathname } from '../../runtime';
import './styles.css';

const PRIMARY_ACTION_LABEL = 'New event';
const WIDGET_ID = 'calendar-sidebar-footer';

function CalendarSidebarFooterWidget() {
  const appId = runtimeAppIdFromPathname(window.location.pathname);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState('');

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
        <Plus aria-hidden="true" />
        <span>New event</span>
      </button>
      <button
        className="calendar-sidebar-footer__connect"
        disabled={isConnecting}
        onClick={() => void connectAccount(appId, setIsConnecting, setError)}
        title={error || 'Connect Google Calendar'}
        type="button"
      >
        <CalendarPlus aria-hidden="true" />
        <span>{isConnecting ? 'Connecting' : 'Connect'}</span>
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

async function connectAccount(appId: string, setIsConnecting: (value: boolean) => void, setError: (value: string) => void) {
  const authorizationWindow = openBlankAuthorizationWindow();
  setIsConnecting(true);
  setError('');
  try {
    const started = await startGoogleOAuth(appId, { redirectUri: calendarOAuthRedirectUri(appId, window.location.origin) });
    openAuthorizationUrl(started.authorization_url, authorizationWindow);
  } catch (connectError) {
    closeAuthorizationWindow(authorizationWindow);
    setError(connectError instanceof Error ? connectError.message : 'Google Calendar connection failed.');
  } finally {
    setIsConnecting(false);
  }
}

function openBlankAuthorizationWindow() {
  const popup = window.open('about:blank', '_blank');
  if (!popup) {
    return null;
  }
  try {
    popup.document.title = 'Opening Google Calendar';
    popup.document.body.style.fontFamily = 'system-ui, sans-serif';
    popup.document.body.style.padding = '24px';
    popup.document.body.textContent = 'Opening Google Calendar...';
  } catch {
    return popup;
  }
  return popup;
}

function openAuthorizationUrl(authorizationUrl: string, popup: Window | null) {
  if (popup && !popup.closed) {
    popup.location.replace(authorizationUrl);
    try {
      popup.opener = null;
      popup.focus();
    } catch {
      return;
    }
    return;
  }
  if (window.top && window.top !== window) {
    window.parent.postMessage({ type: 'maverick.app.external-url', url: authorizationUrl }, window.location.origin);
    return;
  }
  window.location.assign(authorizationUrl);
}

function closeAuthorizationWindow(popup: Window | null) {
  if (popup && !popup.closed) {
    try {
      popup.close();
    } catch {
      return;
    }
  }
}

createRoot(document.getElementById('calendar-sidebar-footer-root') as HTMLElement).render(<CalendarSidebarFooterWidget />);
