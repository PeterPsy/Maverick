import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createDynamicView, deleteDynamicView, listDynamicViews, toDynamicViewPayload } from './api';
import { DynamicViewFrame } from './dynamicViewFrame';
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

  async function refresh() {
    const payload = await listDynamicViews();
    setItems(payload.items);
    setSelectedId((current) => current || payload.items[0]?.id || '');
  }

  useEffect(() => {
    refresh().catch((loadError: Error) => setError(loadError.message));
  }, []);

  const selected = useMemo(() => items.find((item) => item.id === selectedId) || items[0] || null, [items, selectedId]);

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
      await refresh();
      setSelectedId(created.instance.id);
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
      <header className="dv-topbar">
        <div>
          <p className="dv-eyebrow">Workspace Library</p>
          <h1>Dynamic Views</h1>
        </div>
        <button className="dv-icon-button" onClick={() => refresh().catch((refreshError: Error) => setError(refreshError.message))} aria-label="Refresh">
          <span className="material-symbols-rounded" aria-hidden="true">refresh</span>
        </button>
      </header>

      {error ? <div className="dv-error">{error}</div> : null}

      <section className="dv-layout">
        <aside className="dv-library" aria-label="Saved dynamic views">
          <div className="dv-section-head">
            <p className="dv-eyebrow">Saved</p>
            <strong>{items.length} views</strong>
          </div>
          <div className="dv-card-list">
            {items.map((item) => (
              <button key={item.id} className={item.id === selected?.id ? 'dv-card selected' : 'dv-card'} onClick={() => setSelectedId(item.id)}>
                <span className="dv-card-icon material-symbols-rounded" aria-hidden="true">dashboard_customize</span>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.summary || item.id}</small>
                </span>
                <span className="dv-pill">{item.snapshot_mode}</span>
              </button>
            ))}
            {!items.length ? <p className="dv-empty">No dynamic views saved yet.</p> : null}
          </div>
        </aside>

        <section className="dv-editor" aria-label="Create dynamic view">
          <div className="dv-section-head">
            <p className="dv-eyebrow">Create</p>
            <button className="dv-primary" onClick={createView} disabled={busy}>
              <span className="material-symbols-rounded" aria-hidden="true">add</span>
              Save
            </button>
          </div>
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
        </section>

        <section className="dv-preview" aria-label="Dynamic view preview">
          <div className="dv-section-head">
            <div>
              <p className="dv-eyebrow">Preview</p>
              <strong>{selected?.title || 'Select a view'}</strong>
            </div>
            {selected ? (
              <button className="dv-icon-button" onClick={() => removeView(selected.id)} disabled={busy} aria-label="Delete selected view">
                <span className="material-symbols-rounded" aria-hidden="true">delete</span>
              </button>
            ) : null}
          </div>
          {selected ? <DynamicViewFrame payload={toDynamicViewPayload(selected)} /> : <p className="dv-empty">Create or select a saved dynamic view.</p>}
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root') as HTMLElement).render(<App />);
