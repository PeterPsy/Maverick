import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { readDynamicView, toDynamicViewPayload } from '../../api';
import { DynamicViewFrame } from '../../dynamicViewFrame';
import type { DynamicViewPayload } from '../../types';
import './styles.css';

type WidgetContext = {
  content?: {
    payload?: Record<string, unknown>;
  };
};

function contextToken() {
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get('context') || new URLSearchParams(window.location.search).get('context') || '';
}

async function loadWidgetContext(): Promise<WidgetContext> {
  const token = contextToken();
  if (!token) throw new Error('Missing widget context.');
  const response = await fetch(`/api/apps/widgets/context/${encodeURIComponent(token)}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) throw new Error('Unable to load widget context.');
  return (await response.json()).context as WidgetContext;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function payloadHasPackage(payload: Record<string, unknown>): payload is DynamicViewPayload & Record<string, unknown> {
  const pkg = payload.package;
  return typeof pkg === 'object' && pkg !== null && typeof (pkg as Record<string, unknown>).html === 'string';
}

function openDynamicViews(instanceId?: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'dynamic-views',
      params: instanceId ? { app_page: `views/${encodeURIComponent(instanceId)}`, instance_id: instanceId, view_id: instanceId } : {}
    },
    window.location.origin
  );
}

function DynamicViewWidget() {
  const [payload, setPayload] = useState<DynamicViewPayload | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    loadWidgetContext()
      .then(async (context) => {
        const contentPayload = context.content?.payload || {};
        if (payloadHasPackage(contentPayload)) return contentPayload;
        const instanceId = firstString(contentPayload.instanceId, contentPayload.id, contentPayload.instance_id);
        if (!instanceId) throw new Error('Dynamic view instance id is missing.');
        const result = await readDynamicView(instanceId);
        return toDynamicViewPayload(result.instance);
      })
      .then((nextPayload) => setPayload(nextPayload))
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  const meta = useMemo(() => {
    if (!payload) return [];
    return [payload.snapshotMode, payload.package.renderer, ...(payload.package.tags || []).slice(0, 3)];
  }, [payload]);

  if (error) return <main className="dv-widget"><p className="dv-widget__empty">{error}</p></main>;
  if (!payload) return <main className="dv-widget"><p className="dv-widget__empty">Loading dynamic view...</p></main>;

  return (
    <main className="dv-widget">
      <header className="dv-widget__head">
        <span className="dv-widget__icon material-symbols-rounded" aria-hidden="true">dashboard_customize</span>
        <span className="dv-widget__title">
          <p className="dv-widget__eyebrow">Dynamic view</p>
          <h3>{payload.title}</h3>
          {payload.summary ? <p>{payload.summary}</p> : null}
        </span>
        <button className="dv-widget__open" onClick={() => openDynamicViews(payload.instanceId || payload.id)} aria-label="Open in Dynamic Views">
          <span className="material-symbols-rounded" aria-hidden="true">open_in_new</span>
        </button>
      </header>
      <DynamicViewFrame payload={payload} />
      <footer className="dv-widget__meta">
        {meta.map((item) => <span key={item}>{item}</span>)}
      </footer>
    </main>
  );
}

createRoot(document.getElementById('dynamic-view-widget-root') as HTMLElement).render(<DynamicViewWidget />);
