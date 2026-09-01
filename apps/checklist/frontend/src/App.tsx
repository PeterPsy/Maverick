import { useEffect, useMemo, useRef, useState } from 'react';
import { listChecklists, readChecklist } from './api';
import { ChecklistAppSkeleton } from './components/ChecklistLoadingSkeletons';
import { ChecklistPlansGrid } from './components/ChecklistPlansGrid';
import Plan from './components/ui/agent-plan';
import { notifyActiveChecklistSelection } from './lib/activeChecklistSelection';
import { checklistIdFromParams, isChecklistBoardParams } from './lib/checklistNavigationParams';
import type { ChecklistItem } from './types';

const APP_EVENTS_WS_PATH = '/api/apps/events/ws';
type ChecklistViewMode = 'board' | 'detail';

function initialChecklistId() {
  const query = new URLSearchParams(window.location.search);
  return query.get('checklist_id') || '';
}

function initialViewMode(): ChecklistViewMode {
  return initialChecklistId() ? 'detail' : 'board';
}

function selectedChecklistIdFromItems(
  items: ChecklistItem[],
  currentChecklistId: string,
  preferredChecklistId?: string,
  allowFallback = true
) {
  if (preferredChecklistId && items.some((item) => item.id === preferredChecklistId)) {
    return preferredChecklistId;
  }
  if (currentChecklistId && items.some((item) => item.id === currentChecklistId)) {
    return currentChecklistId;
  }
  return allowFallback ? items[0]?.id || '' : '';
}

function isChecklistCompleted(item: ChecklistItem) {
  return item.status === 'completed' || (item.task_count > 0 && item.checked_count >= item.task_count);
}

export function App() {
  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [viewMode, setViewMode] = useState<ChecklistViewMode>(initialViewMode);
  const [selectedId, setSelectedId] = useState<string>(initialChecklistId);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const selectedIdRef = useRef(initialChecklistId());
  const viewModeRef = useRef<ChecklistViewMode>(initialViewMode());

  const selected = useMemo(() => items.find((item) => item.id === selectedId) || null, [items, selectedId]);
  const selectedTasks = useMemo(() => selected?.sections.flatMap((section) => section.tasks) || [], [selected]);

  const load = async (preferredChecklistId?: string, nextViewMode?: ChecklistViewMode) => {
    setLoading(true);
    setError('');
    try {
      const activeViewMode = nextViewMode || viewModeRef.current;
      let nextItems = await listChecklists({ ignoreViewState: activeViewMode === 'board' });
      const selectedFallbackId = preferredChecklistId || selectedIdRef.current;
      if (selectedFallbackId && !nextItems.some((item) => item.id === selectedFallbackId)) {
        try {
          const selectedItem = await readChecklist(selectedFallbackId);
          nextItems = [selectedItem, ...nextItems];
        } catch {
          // The selected checklist may have been deleted; fall back to the visible list.
        }
      }
      setItems(nextItems);
      setSelectedId((current) =>
        selectedChecklistIdFromItems(
          nextItems,
          current,
          preferredChecklistId,
          activeViewMode === 'detail' || Boolean(selectedFallbackId)
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Checklist load failed.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    viewModeRef.current = viewMode;
  }, [viewMode]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'checklist' }, "*");
  }, []);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
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
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'checklist')) {
        void handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type !== 'maverick.app.data-changed' || payload.owner_app_id !== 'checklist') {
        return;
      }
      if (!payload.resource || payload.resource === 'state') {
        void load(selectedIdRef.current || undefined);
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [items]);

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
          if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'checklist') {
            void load(selectedIdRef.current || undefined);
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
    if (selectedId) {
      notifyActiveChecklistSelection(selectedId);
    }
  }, [selectedId]);

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedChecklistId = checklistIdFromParams(params);
    if (requestedChecklistId) {
      setViewMode('detail');
      viewModeRef.current = 'detail';
      if (items.some((item) => item.id === requestedChecklistId)) {
        setSelectedId(requestedChecklistId);
      } else {
        await load(requestedChecklistId, 'detail');
      }
      return;
    }
    if (isChecklistBoardParams(params)) {
      selectedIdRef.current = '';
      setSelectedId('');
      setViewMode('board');
      viewModeRef.current = 'board';
      await load(undefined, 'board');
    }
  };

  function openChecklist(item: ChecklistItem) {
    selectedIdRef.current = item.id;
    setSelectedId(item.id);
    setViewMode('detail');
    window.parent?.postMessage(
      {
        type: 'maverick.app.open-app',
        app_id: 'checklist',
        params: {
          app_page: `checklists/${item.id}`,
          checklist_id: item.id
        }
      },
      "*"
    );
  }

  return (
    <main className="checklist-app">
      {error ? <div className="checklist-error">{error}</div> : null}
      {loading ? <ChecklistAppSkeleton viewMode={viewMode} /> : null}
      {!loading && viewMode === 'board' && !items.length ? (
        <div className="checklist-empty">No agent plans yet.</div>
      ) : null}
      {!loading && viewMode === 'board' && items.length ? (
        <ChecklistPlansGrid items={items} onOpenChecklist={openChecklist} />
      ) : null}
      {!loading && viewMode === 'detail' && !selected ? (
        <div className="checklist-empty">No agent plan selected.</div>
      ) : null}
      {!loading && viewMode === 'detail' && selected ? (
        <>
          <header className="detail-header checklist-detail-header">
            <div className="detail-title-block">
              <h2 className={isChecklistCompleted(selected) ? 'is-completed' : ''}>{selected.title || 'Checklist'}</h2>
              <span className="detail-title-separator" aria-hidden="true" />
              <p>{selected.summary || `${selected.checked_count}/${selected.task_count} checked`}</p>
            </div>
          </header>
          <div className="checklist-detail-board">
            <Plan
              tasks={selectedTasks}
              readonly
            />
          </div>
        </>
      ) : null}
    </main>
  );
}
