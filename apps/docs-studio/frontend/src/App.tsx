import { useEffect, useMemo, useRef, useState } from 'react';
import { loadDocsState } from './api';
import { Markdown } from './Markdown';
import { notifyActiveDocSelection } from './lib/activeDocSelection';
import { docPageIdFromParams } from './lib/docNavigationParams';
import type { DocsPage, DocsSection, DocsState } from './types';

const APP_EVENTS_WS_PATH = '/api/apps/events/ws';

interface ActivePage {
  section: DocsSection;
  page: DocsPage;
}

function findFirstPage(state: DocsState | null): ActivePage | null {
  for (const section of state?.sections || []) {
    const page = section.pages[0];
    if (page) {
      return { section, page };
    }
  }
  return null;
}

function findPage(state: DocsState | null, pageId: string): ActivePage | null {
  for (const section of state?.sections || []) {
    for (const page of section.pages || []) {
      if (page.id === pageId) {
        return { section, page };
      }
    }
  }
  return null;
}

function initialPageId() {
  const query = new URLSearchParams(window.location.search);
  return query.get('page_id') || '';
}

function selectedPageIdFromState(state: DocsState, currentPageId: string, preferredPageId?: string) {
  if (preferredPageId && findPage(state, preferredPageId)) {
    return preferredPageId;
  }
  if (currentPageId && findPage(state, currentPageId)) {
    return currentPageId;
  }
  return findFirstPage(state)?.page.id || '';
}

export function App() {
  const [state, setState] = useState<DocsState | null>(null);
  const [activePageId, setActivePageId] = useState(initialPageId);
  const [notice, setNotice] = useState('');
  const activePageIdRef = useRef(initialPageId());

  const active = useMemo(() => findPage(state, activePageId) || findFirstPage(state), [state, activePageId]);

  async function refresh(preferredPageId?: string) {
    try {
      const loaded = await loadDocsState();
      const nextPageId = selectedPageIdFromState(loaded, activePageIdRef.current, preferredPageId);
      activePageIdRef.current = nextPageId;
      setState(loaded);
      setActivePageId(nextPageId);
      setNotice('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Docs Studio load failed.');
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    activePageIdRef.current = activePageId;
  }, [activePageId]);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timer = window.setTimeout(() => setNotice(''), 2800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'docs-studio' }, window.location.origin);
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: Record<string, string | boolean | null>;
        resource?: string;
        type?: string;
      };
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'docs-studio')) {
        const requestedPageId = docPageIdFromParams(payload.params || {});
        if (requestedPageId) {
          if (findPage(state, requestedPageId)) {
            activePageIdRef.current = requestedPageId;
            setActivePageId(requestedPageId);
          } else {
            void refresh(requestedPageId);
          }
        }
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'docs-studio') {
        if (!payload.resource || payload.resource === 'state') {
          void refresh(activePageIdRef.current || undefined);
        }
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [state]);

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
          const payload = JSON.parse(message.data) as { type?: string; owner_app_id?: string; resource?: string };
          if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'docs-studio' && (!payload.resource || payload.resource === 'state')) {
            void refresh(activePageIdRef.current || undefined);
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

  useEffect(() => {
    if (activePageId) {
      notifyActiveDocSelection(activePageId);
    }
  }, [activePageId]);

  if (!state || !active) {
    return <div className="loading">Loading Docs Studio...</div>;
  }

  return (
    <main className="docs-app">
      <article className="doc-page">
        <header className="doc-header">
          <p className="eyebrow">{active.section.title}</p>
          <h1>{active.page.title}</h1>
          <p className="lead">{active.page.summary || state.site.tagline}</p>
        </header>

        <section className="markdown-preview" aria-label="Documentation body">
          <Markdown markdown={active.page.body} />
        </section>
      </article>

      <div className={`notice ${notice ? 'visible' : ''}`} role="status">{notice}</div>
    </main>
  );
}
