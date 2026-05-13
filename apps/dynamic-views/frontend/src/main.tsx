import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createDynamicView, deleteDynamicView, listDynamicViews, toDynamicViewPayload } from './api';
import { DynamicViewFrame } from './dynamicViewFrame';
import { notifyActiveDynamicViewSelection } from './lib/activeDynamicViewSelection';
import { dynamicViewIdFromParams } from './lib/dynamicViewNavigationParams';
import type { DynamicViewInstance } from './types';
import './styles/main.css';

const DEFAULT_HTML = `<main class="view">
  <h1>Quick dynamic card</h1>
  <div id="dynamic-root"></div>
</main>`;
const DEFAULT_CSS = `body { margin: 0; color: #111827; font-family: system-ui; }
.view { padding: 22px; }
#dynamic-root { white-space: pre-wrap; font-family: ui-monospace, monospace; }`;
const DEFAULT_JS = `const root = document.getElementById("dynamic-root");
const data = window.MaverickDynamicView?.data || {};
root.textContent = JSON.stringify(data, null, 2);`;
const DEFAULT_DATA = '{\n  "headline": "Revenue",\n  "value": 42,\n  "delta": "+18%"\n}';

function initialDynamicViewId() {
  const query = new URLSearchParams(window.location.search);
  return dynamicViewIdFromParams({
    app_page: query.get('app_page'),
    id: query.get('id'),
    instance_id: query.get('instance_id'),
    view_id: query.get('view_id')
  });
}

function selectedDynamicViewIdFromItems(items: DynamicViewInstance[], currentViewId: string, preferredViewId?: string) {
  if (preferredViewId && items.some((item) => item.id === preferredViewId)) {
    return preferredViewId;
  }
  if (currentViewId && items.some((item) => item.id === currentViewId)) {
    return currentViewId;
  }
  return items[0]?.id || '';
}

function App() {
  const [items, setItems] = useState<DynamicViewInstance[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [title, setTitle] = useState('Quick dynamic card');
  const [summary, setSummary] = useState('Example persisted dynamic view.');
  const [html, setHtml] = useState(DEFAULT_HTML);
  const [css, setCss] = useState(DEFAULT_CSS);
  const [javascript, setJavascript] = useState(DEFAULT_JS);
  const [dataJson, setDataJson] = useState(DEFAULT_DATA);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const selectedIdRef = useRef('');

  async function refresh(preferredViewId?: string) {
    setIsLoading(true);
    try {
      const payload = await listDynamicViews();
      const nextSelectedId = selectedDynamicViewIdFromItems(payload.items, selectedIdRef.current, preferredViewId);
      selectedIdRef.current = nextSelectedId;
      setItems(payload.items);
      setSelectedId(nextSelectedId);
      return nextSelectedId;
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    refresh(initialDynamicViewId()).catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'dynamic-views' }, window.location.origin);
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
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'dynamic-views')) {
        void handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'dynamic-views' && payload.resource === 'views') {
        void refresh(selectedIdRef.current).catch((refreshError: Error) => setError(refreshError.message));
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [items]);

  useEffect(() => {
    if (selectedId) {
      notifyActiveDynamicViewSelection(selectedId);
    }
  }, [selectedId]);

  const selected = useMemo(() => items.find((item) => item.id === selectedId) || items[0] || null, [items, selectedId]);

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedViewId = dynamicViewIdFromParams(params);
    if (!requestedViewId) {
      return;
    }
    if (items.some((item) => item.id === requestedViewId)) {
      setSelectedId(requestedViewId);
    } else {
      await refresh(requestedViewId);
    }
  }

  async function createView() {
    setBusy(true);
    setError('');
    try {
      const data = JSON.parse(dataJson) as Record<string, unknown>;
      const created = await createDynamicView({
        title,
        summary,
        package: { renderer: 'sandbox_html_v1', html, css, javascript },
        data,
        dataBindings: [{ sourceType: 'inline', sourceRef: `${title.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'dynamic-view'}-seed`, snapshot: data }],
        snapshotMode: 'snapshot'
      });
      await refresh(created.instance.id);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : 'Unable to create dynamic view.');
    } finally {
      setBusy(false);
    }
  }

  async function removeView(instanceId: string) {
    setBusy(true);
    setError('');
    try {
      await deleteDynamicView(instanceId);
      selectedIdRef.current = '';
      setSelectedId('');
      await refresh();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Unable to delete dynamic view.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="dv-shell">
      <section className="dv-detail">
        <header className="detail-header">
          <div className="detail-title-block">
            <h2>{selected?.title || 'Dynamic Views'}</h2>
            <span className="detail-title-separator" aria-hidden="true" />
            <p>{selected?.summary || 'Workspace Library'}</p>
          </div>
          <div className="action-group">
            <button className="secondary-action" onClick={() => refresh().catch((refreshError: Error) => setError(refreshError.message))} type="button">
              <span className="material-symbols-rounded" aria-hidden="true">refresh</span>
              Refresh
            </button>
            <button className="danger-action" onClick={() => selected && removeView(selected.id)} disabled={!selected || busy} type="button">
              <span className="material-symbols-rounded" aria-hidden="true">delete</span>
              Delete View
            </button>
            <button className="primary-action" onClick={createView} disabled={busy} type="button">
              <span className="material-symbols-rounded" aria-hidden="true">save</span>
              {busy ? 'Saving View' : 'Save View'}
            </button>
          </div>
        </header>

        {error ? <div className="dv-error">{error}</div> : null}

        <section className="dv-layout">
          <section className="dv-editor dv-card-panel" aria-label="Create dynamic view">
            <div className="dv-section-head">
              <span>
                <p className="dv-eyebrow">Create</p>
                <strong>Sandbox HTML view</strong>
              </span>
              <span className="dv-pill">{items.length} saved</span>
            </div>
            <div className="dv-editor-fields">
              <label>
                <span>Title</span>
                <input value={title} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <label>
                <span>Summary</span>
                <input value={summary} onChange={(event) => setSummary(event.target.value)} />
              </label>
              <label>
                <span>HTML</span>
                <textarea value={html} rows={6} onChange={(event) => setHtml(event.target.value)} />
              </label>
              <label>
                <span>CSS</span>
                <textarea value={css} rows={5} onChange={(event) => setCss(event.target.value)} />
              </label>
              <label>
                <span>JavaScript</span>
                <textarea value={javascript} rows={7} onChange={(event) => setJavascript(event.target.value)} />
              </label>
              <label>
                <span>Data JSON</span>
                <textarea value={dataJson} rows={6} onChange={(event) => setDataJson(event.target.value)} />
              </label>
            </div>
          </section>

          <section className="dv-preview dv-card-panel" aria-label="Dynamic view preview">
            <div className="dv-section-head">
              <span>
                <p className="dv-eyebrow">Preview</p>
                <strong>{selected?.title || (isLoading ? 'Loading views' : 'No view selected')}</strong>
              </span>
            </div>
            <div className="dv-preview-body">
              {selected ? <DynamicViewFrame payload={toDynamicViewPayload(selected)} /> : <p className="dv-empty">Create or select a saved dynamic view.</p>}
            </div>
          </section>
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root') as HTMLElement).render(<App />);
