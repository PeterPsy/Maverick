import { useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { CheckSquare, Search } from 'lucide-react';
import { listChecklists, readViewFilter, setViewFilter } from '../../api';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import {
  checklistIdFromSelectionMessage,
  checklistIdFromWidgetContext,
  type ActiveChecklistSelectionMessage
} from '../../lib/activeChecklistSelection';
import { checklistDragPayloadFromItem, writeChecklistDragData } from '../../lib/checklistDragDrop';
import type { ChecklistItem } from '../../types';
import '../../styles/sidebar-widget.css';

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

function isMobileLayoutViewport() {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === 'function' && shellWindow.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  } catch {
    return typeof window.matchMedia === 'function' && window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  }
}

function useShellMobileLayout() {
  const [isShellMobileLayout, setIsShellMobileLayout] = useState(isMobileLayoutViewport);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    let mediaQuery: MediaQueryList;
    try {
      const shellWindow = window.parent && window.parent !== window ? window.parent : window;
      mediaQuery = shellWindow.matchMedia(MOBILE_LAYOUT_QUERY);
    } catch {
      mediaQuery = window.matchMedia(MOBILE_LAYOUT_QUERY);
    }
    const update = () => setIsShellMobileLayout(mediaQuery.matches);
    update();
    mediaQuery.addEventListener('change', update);
    return () => mediaQuery.removeEventListener('change', update);
  }, []);

  return isShellMobileLayout;
}

function openChecklistInShell(checklistId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'checklist',
      params: {
        app_page: `checklists/${checklistId}`,
        checklist_id: checklistId
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function checklistMatchesSearch(item: ChecklistItem, query: string) {
  if (!query) return true;
  const taskText = item.sections
    .flatMap((section) => section.tasks)
    .map((task) => `${task.title} ${task.description}`)
    .join(' ');
  return `${item.title} ${item.summary} ${item.mode} ${taskText}`.toLowerCase().includes(query);
}

function ChecklistSidebarWidget() {
  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [query, setQuery] = useState('');
  const [selectedChecklistId, setSelectedChecklistId] = useState('');
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const lastPersistedQueryRef = useRef('');
  const hasLoadedViewStateRef = useRef(false);

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredItems = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => checklistMatchesSearch(item, needle));
  }, [items, query]);

  async function refreshItems() {
    const next = await listChecklists();
    setItems(next);
    setSelectedChecklistId((current) => {
      if (current && next.some((item) => item.id === current)) {
        return current;
      }
      return next[0]?.id || '';
    });
  }

  async function refreshViewFilter() {
    const payload = await readViewFilter();
    const nextQuery = payload.query || '';
    lastPersistedQueryRef.current = nextQuery;
    hasLoadedViewStateRef.current = true;
    setQuery(nextQuery);
  }

  async function refreshAll() {
    try {
      await Promise.all([refreshItems(), refreshViewFilter()]);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load checklists.');
    } finally {
      setIsInitialLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    if (!hasLoadedViewStateRef.current || query === lastPersistedQueryRef.current) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const nextQuery = query.trim();
      setViewFilter(nextQuery)
        .then(() => {
          lastPersistedQueryRef.current = nextQuery;
          setError(null);
          return refreshItems();
        })
        .catch((saveError: Error) => setError(saveError.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        context?: Record<string, unknown>;
        owner_app_id?: string;
        resource?: string;
        type?: string;
      } & ActiveChecklistSelectionMessage;
      const contextChecklistId = checklistIdFromWidgetContext(payload);
      if (contextChecklistId) {
        setSelectedChecklistId(contextChecklistId);
        return;
      }
      const activeChecklistId = checklistIdFromSelectionMessage(payload);
      if (activeChecklistId) {
        setSelectedChecklistId(activeChecklistId);
        return;
      }
      if (
        (payload.type !== 'maverick.widget.data-changed' && payload.type !== 'maverick.app.data-changed') ||
        payload.owner_app_id !== 'checklist'
      ) {
        return;
      }
      if (payload.resource === 'state') {
        void refreshItems();
      }
      if (payload.resource === 'view-state') {
        void refreshViewFilter();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  function selectChecklist(item: ChecklistItem) {
    setSelectedChecklistId(item.id);
    openChecklistInShell(item.id);
  }

  function handleChecklistDragStart(event: DragEvent<HTMLElement>, item: ChecklistItem) {
    writeChecklistDragData(event.dataTransfer, checklistDragPayloadFromItem(item));
  }

  return (
    <main className={`checklist-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="checklist-sidebar-search-frame">
        <Search size={17} aria-hidden="true" />
        <input
          aria-label="Search checklists"
          className="checklist-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search checklists"
          value={query}
        />
      </div>

      {error ? <p className="checklist-sidebar-empty">{error}</p> : null}

      <div className="checklist-sidebar-list">
        {isInitialLoading ? (
          <ChecklistSidebarSkeleton />
        ) : filteredItems.length ? (
          filteredItems.map((item) => {
            const isCompleted =
              item.status === 'completed' || (item.task_count > 0 && item.checked_count >= item.task_count);

            return (
              <button
                className={`checklist-sidebar-row ${item.id === selectedChecklistId ? 'is-active' : ''}`}
                draggable
                key={item.id}
                onDragStart={(event) => handleChecklistDragStart(event, item)}
                onClick={() => selectChecklist(item)}
                type="button"
              >
                <span className="checklist-sidebar-row__icon" aria-hidden="true">
                  <CheckSquare size={17} />
                </span>
                <span className="checklist-sidebar-row__copy">
                  <strong className={isCompleted ? 'is-completed' : ''}>{item.title || 'Checklist'}</strong>
                  <span>
                    {item.mode.replace('_', ' ')} · {item.checked_count}/{item.task_count}
                  </span>
                </span>
              </button>
            );
          })
        ) : (
          <p className="checklist-sidebar-empty">No checklists found.</p>
        )}
      </div>
    </main>
  );
}

function ChecklistSidebarSkeleton() {
  return (
    <div aria-hidden="true" className="checklist-sidebar-skeleton">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="checklist-sidebar-skeleton__row" key={index}>
          <span className="checklist-sidebar-skeleton__icon" />
          <span className="checklist-sidebar-skeleton__copy">
            <span />
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('checklist-sidebar-root') as HTMLElement).render(<ChecklistSidebarWidget />);
