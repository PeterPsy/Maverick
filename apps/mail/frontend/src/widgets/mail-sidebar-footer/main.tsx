import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Link } from 'lucide-react';
import { callBackend, MAIL_BACKEND_ACTIONS } from '../../api';
import './styles.css';

const DEFAULT_APP_ID = 'mail';
const PRIMARY_ACTION_LABEL = 'Add account';
const WIDGET_ID = 'mail-sidebar-footer';

function postPrimaryActionState(appId: string, available: boolean) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.primary-action.state',
      owner_app_id: appId,
      widget_id: WIDGET_ID,
      available,
      label: PRIMARY_ACTION_LABEL
    },
    window.location.origin
  );
}

function notifyMailConnectionsChanged(appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.data-changed',
      owner_app_id: appId,
      resource: 'connections'
    },
    window.location.origin
  );
}

async function startGmailOAuth(appId: string) {
  const redirectUri = `${window.location.origin}/apps/mail/oauth/callback`;
  const payload = await callBackend<{ status: string; authorization_url?: string; detail?: string }>({
    action: MAIL_BACKEND_ACTIONS.connectionsStartOAuth,
    provider: 'gmail',
    redirect_uri: redirectUri,
    _app_secret_request: {
      logical_names: ['gmail-oauth-client-id'],
      required: false
    }
  });
  if (payload.authorization_url) {
    window.open(payload.authorization_url, '_blank', 'noopener,noreferrer');
  }
  notifyMailConnectionsChanged(appId);
  return payload;
}

function MailSidebarFooterWidget() {
  const appId = currentMailAppId();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    postPrimaryActionState(appId, !busy);
  }, [appId, busy]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        owner_app_id?: string;
        type?: string;
        widget_id?: string;
      };
      if (
        payload.owner_app_id === appId &&
        payload.widget_id === WIDGET_ID &&
        payload.type === 'maverick.widget.primary-action.query'
      ) {
        postPrimaryActionState(appId, !busy);
        return;
      }
      if (
        payload.owner_app_id === appId &&
        payload.widget_id === WIDGET_ID &&
        payload.type === 'maverick.widget.primary-action.invoke'
      ) {
        connectAccount();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId, busy]);

  async function connectAccount() {
    if (busy) {
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const payload = await startGmailOAuth(appId);
      setNotice(payload.detail || `Gmail OAuth status: ${payload.status}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Gmail connection failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mail-sidebar-footer-widget">
      <button
        aria-label={PRIMARY_ACTION_LABEL}
        className="mail-sidebar-footer__add-account"
        disabled={busy}
        onClick={connectAccount}
        title={notice || PRIMARY_ACTION_LABEL}
        type="button"
      >
        <Link size={16} strokeWidth={1.8} aria-hidden="true" />
        <span>{PRIMARY_ACTION_LABEL}</span>
      </button>
    </main>
  );
}

function currentMailAppId(pathname = typeof window === 'undefined' ? '' : window.location.pathname): string {
  return mountedAppIdFromPath(pathname, DEFAULT_APP_ID);
}

function mountedAppIdFromPath(pathname: string, fallback: string): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) {
    return fallback;
  }
  try {
    return decodeURIComponent(match[1]) || fallback;
  } catch {
    return match[1] || fallback;
  }
}

createRoot(document.getElementById('mail-sidebar-footer-root') as HTMLElement).render(<MailSidebarFooterWidget />);
