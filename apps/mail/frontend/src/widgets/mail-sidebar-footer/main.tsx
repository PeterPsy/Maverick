import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Plus } from 'lucide-react';
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

function openAccountModal(appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params: {
        add_account: true,
        add_account_request_id: crypto.randomUUID()
      }
    },
    window.location.origin
  );
}

function MailSidebarFooterWidget() {
  const appId = currentMailAppId();
  const [busy, setBusy] = useState(false);

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
        openAddAccount();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId, busy]);

  function openAddAccount() {
    if (busy) {
      return;
    }
    setBusy(true);
    openAccountModal(appId);
    window.setTimeout(() => {
      setBusy(false);
    }, 250);
  }

  return (
    <main className="mail-sidebar-footer-widget">
      <button
        aria-label={PRIMARY_ACTION_LABEL}
        className="mail-sidebar-footer__add-account"
        disabled={busy}
        onClick={openAddAccount}
        title={PRIMARY_ACTION_LABEL}
        type="button"
      >
        <Plus size={16} strokeWidth={1.8} aria-hidden="true" />
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
