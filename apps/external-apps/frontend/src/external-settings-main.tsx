import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { App } from './App';
import { appId } from './api';
import './styles.css';
import './external-settings.css';

function ExternalSettings() {
  const [source, setSource] = useState<{ id: string; name: string }>();
  useEffect(() => {
    function message(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event) || event.data?.type !== 'maverick.widget.context-changed'
          || event.data.owner_app_id !== appId || event.data.widget_id !== 'external-surfaces-settings') return;
      const content = event.data.context?.content;
      const payload = content?.payload;
      if (content?.kind !== 'shell.app.external.surfaces' || typeof payload?.app_id !== 'string'
          || !payload.app_id || payload.app_id.length > 128) { setSource(undefined); return; }
      const theme = content.shell_theme?.effective;
      if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
      setSource({ id: payload.app_id, name: typeof payload.app_name === 'string' ? payload.app_name.slice(0, 120) : payload.app_id });
    }
    window.addEventListener('message', message);
    window.parent.postMessage({ type: 'maverick.widget.ready', owner_app_id: appId, widget_id: 'external-surfaces-settings' }, '*');
    return () => window.removeEventListener('message', message);
  }, []);
  return source ? <App key={source.id} sourceAppId={source.id} sourceAppName={source.name} /> : <p className="empty" role="status">Caricamento del contesto app…</p>;
}

document.documentElement.classList.add('external-settings');
createRoot(document.getElementById('root')!).render(<StrictMode><ExternalSettings /></StrictMode>);
