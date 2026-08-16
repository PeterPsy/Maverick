import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import AgentPlan from './components/ui/agent-plan';
import { ChecklistWidgetSkeleton } from './components/ChecklistLoadingSkeletons';
import { useTransientOverlayScrollbar } from './components/useTransientOverlayScrollbar';
import { loadWidgetContext, readChecklist } from './api';
import type { ChecklistItem } from './types';
import './styles/main.css';

const APP_ID = 'checklist';
const WIDGET_ID = 'design-checklist';
const APP_EVENTS_WS_PATH = '/api/apps/events/ws';

function Widget() {
  const [checklistId, setChecklistId] = useState('');
  const [item, setItem] = useState<ChecklistItem | null>(null);
  const [error, setError] = useState('');
  const frameRef = useRef<HTMLElement | null>(null);
  const lastHeightRef = useRef<number | null>(null);
  const {
    handleScroll,
    isScrolling,
    refreshScrollbarMetrics,
    scrollRef,
    scrollbarMetrics
  } = useTransientOverlayScrollbar();
  const tasks = useMemo(() => item?.sections.flatMap((section) => section.tasks) || [], [item]);

  const load = async (knownId = checklistId) => {
    try {
      let id = knownId;
      if (!id) {
        const token = contextToken();
        if (!token) {
          throw new Error('Missing widget context.');
        }
        const context = await loadWidgetContext(token);
        id = idFromContext(context);
        setChecklistId(id);
      }
      if (!id) {
        throw new Error('Checklist id missing from widget context.');
      }
      setItem(await readChecklist(id));
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load checklist.');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const resize = () => {
      const frame = frameRef.current;
      if (!frame) {
        return;
      }
      const scrollElement = scrollRef.current;
      const fixedHeight = scrollElement
        ? Math.max(0, frame.getBoundingClientRect().height - scrollElement.getBoundingClientRect().height)
        : 0;
      const contentHeight = scrollElement ? fixedHeight + scrollElement.scrollHeight : frame.scrollHeight;
      const nextHeight = Math.ceil(Math.max(frame.scrollHeight, contentHeight));
      refreshScrollbarMetrics();
      if (lastHeightRef.current === nextHeight) {
        return;
      }
      lastHeightRef.current = nextHeight;
      window.parent?.postMessage(
        {
          type: 'maverick.widget.resize',
          owner_app_id: APP_ID,
          widget_id: WIDGET_ID,
          height: `${nextHeight}px`
        },
        window.location.origin
      );
    };
    resize();
    const frame = window.requestAnimationFrame(resize);
    const delayedResize = window.setTimeout(resize, 120);
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
    if (frameRef.current) {
      observer?.observe(frameRef.current);
    }
    if (scrollRef.current) {
      observer?.observe(scrollRef.current);
      if (scrollRef.current.firstElementChild instanceof HTMLElement) {
        observer?.observe(scrollRef.current.firstElementChild);
      }
    }
    window.addEventListener('resize', resize);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(delayedResize);
      observer?.disconnect();
      window.removeEventListener('resize', resize);
    };
  }, [item, error, refreshScrollbarMetrics]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { type?: string; owner_app_id?: string; resource?: string };
      if ((payload.type === 'maverick.widget.data-changed' || payload.type === 'maverick.app.data-changed') && payload.owner_app_id === APP_ID) {
        void load();
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [checklistId]);

  useEffect(() => {
    if (typeof WebSocket === 'undefined') {
      return undefined;
    }
    let closed = false;
    let reconnectTimer = 0;
    let socket: WebSocket | null = null;
    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${window.location.host}${APP_EVENTS_WS_PATH}`);
      socket.onmessage = (message) => {
        try {
          const payload = JSON.parse(message.data) as { type?: string; owner_app_id?: string; resource?: string };
          if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === APP_ID) {
            void load();
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
  }, [checklistId]);

  let content;
  if (error) {
    content = <div className="checklist-widget-error">{error}</div>;
  } else if (!item) {
    content = <ChecklistWidgetSkeleton />;
  } else {
    content = (
      <article className="checklist-widget-card">
        <header className="checklist-widget-card__header">
          <div>
            <p className="checklist-kicker">Checklist</p>
            <h1>{item.title}</h1>
          </div>
          <span>
            {item.checked_count}/{item.task_count}
          </span>
        </header>
        <div className="checklist-widget-scroll-shell">
          <div
            aria-label="Checklist tasks"
            className="checklist-widget-scroll"
            onScroll={handleScroll}
            ref={scrollRef}
            role="region"
            tabIndex={0}
          >
            <AgentPlan tasks={tasks} compact readonly />
          </div>
          {scrollbarMetrics.canScroll ? (
            <span
              aria-hidden="true"
              className={`checklist-widget-scrollbar ${isScrolling ? 'is-scrolling' : ''}`}
            >
              <span
                className="checklist-widget-scrollbar__thumb"
                style={{
                  height: `${scrollbarMetrics.thumbHeight}px`,
                  transform: `translateY(${scrollbarMetrics.thumbOffset}px)`
                }}
              />
            </span>
          ) : null}
        </div>
      </article>
    );
  }
  return (
    <main className="checklist-widget-frame" ref={frameRef}>
      {content}
    </main>
  );
}

function contextToken(): string {
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get('context') || new URLSearchParams(window.location.search).get('context') || '';
}

function idFromContext(context: { content?: { payload?: Record<string, unknown>; memory?: Record<string, unknown> } }): string {
  const payload = context.content?.payload || {};
  const memory = context.content?.memory || {};
  return String(payload.id || payload.checklist_id || memory.checklist_id || '');
}

createRoot(document.getElementById('root') as HTMLElement).render(<Widget />);
