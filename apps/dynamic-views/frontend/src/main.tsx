import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { listDynamicViews, toDynamicViewPayload } from './api';
import { DynamicViewAppSkeleton } from './components/DynamicViewLoadingSkeletons';
import { DynamicViewDetailsDialog } from './DynamicViewDetailsDialog';
import { DynamicViewFrame } from './dynamicViewFrame';
import { notifyActiveDynamicViewSelection } from './lib/activeDynamicViewSelection';
import { dynamicViewIdFromParams } from './lib/dynamicViewNavigationParams';
import { snapshotModeLabel } from './lib/dynamicViewFormatting';
import type { DynamicViewInstance } from './types';
import './styles/main.css';

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

function DynamicViewDetailsButton({
  className = '',
  onOpen,
  view
}: {
  className?: string;
  onOpen: () => void;
  view: DynamicViewInstance | null;
}) {
  return (
    <button
      aria-label={view ? `Open details for ${view.title}` : 'Open dynamic view details'}
      className={`dv-icon-button ${className}`.trim()}
      disabled={!view}
      onClick={onOpen}
      title="Details"
      type="button"
    >
      <span className="material-symbols-rounded" aria-hidden="true">info</span>
    </button>
  );
}

function App() {
  const [items, setItems] = useState<DynamicViewInstance[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const selectedIdRef = useRef('');

  async function loadViews(preferredViewId?: string) {
    setIsLoading(true);
    try {
      const payload = await listDynamicViews();
      const nextSelectedId = selectedDynamicViewIdFromItems(payload.items, selectedIdRef.current, preferredViewId);
      selectedIdRef.current = nextSelectedId;
      setItems(payload.items);
      setSelectedId(nextSelectedId);
      setError('');
      return nextSelectedId;
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadViews(initialDynamicViewId()).catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'dynamic-views' }, "*");
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
        void loadViews(selectedIdRef.current).catch((loadError: Error) => setError(loadError.message));
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
  const showInitialSkeleton = isLoading && !selected && !error;
  const headerSummary = selected?.summary || (
    isLoading
      ? 'Loading saved dynamic views.'
      : items.length
        ? 'Select a saved dynamic view from the sidebar.'
        : 'Views created by Chat and agents will appear here.'
  );

  useEffect(() => {
    if (!selected && isDetailsOpen) {
      setIsDetailsOpen(false);
    }
  }, [isDetailsOpen, selected]);

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedViewId = dynamicViewIdFromParams(params);
    if (!requestedViewId) {
      return;
    }
    if (items.some((item) => item.id === requestedViewId)) {
      setSelectedId(requestedViewId);
    } else {
      await loadViews(requestedViewId);
    }
  }

  return (
    <main className="dv-shell">
      <section className="dv-detail">
        {showInitialSkeleton ? (
          <DynamicViewAppSkeleton />
        ) : (
          <>
            <header className="detail-header">
              <div className="detail-title-block">
                <h2>{selected?.title || 'Dynamic Views'}</h2>
                <span className="detail-title-separator" aria-hidden="true" />
                <p>{headerSummary}</p>
              </div>
              <div className="dv-header-meta" aria-label="Dynamic views summary">
                <span className="dv-pill">{items.length} saved</span>
                {selected ? <span className="dv-pill">{snapshotModeLabel(selected.snapshot_mode)}</span> : null}
                <DynamicViewDetailsButton
                  className="dv-header-info-button"
                  onOpen={() => setIsDetailsOpen(true)}
                  view={selected}
                />
              </div>
            </header>

            {error ? <div className="dv-error">{error}</div> : null}

            <section className="dv-layout dv-viewer-layout">
              <section className="dv-preview dv-card-panel" aria-label="Dynamic view preview">
                <div className="dv-section-head">
                  <span>
                    <p className="dv-eyebrow">Viewer</p>
                    <strong>{selected?.title || (isLoading ? 'Loading views' : 'No view selected')}</strong>
                  </span>
                  <DynamicViewDetailsButton
                    className="dv-viewer-info-button"
                    onOpen={() => setIsDetailsOpen(true)}
                    view={selected}
                  />
                </div>
                <div className="dv-preview-body">
                  {selected ? (
                    <DynamicViewFrame payload={toDynamicViewPayload(selected)} />
                  ) : (
                    <div className="dv-empty">
                      <h3>{isLoading ? 'Loading dynamic views' : 'No dynamic views yet'}</h3>
                      <p>{isLoading ? 'Saved views are being loaded.' : 'Views created by Chat and agents will appear here.'}</p>
                    </div>
                  )}
                </div>
              </section>
            </section>
            <DynamicViewDetailsDialog isOpen={isDetailsOpen} onClose={() => setIsDetailsOpen(false)} view={selected} />
          </>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root') as HTMLElement).render(<App />);
