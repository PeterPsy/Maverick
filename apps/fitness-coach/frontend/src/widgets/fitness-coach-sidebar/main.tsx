import { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Dumbbell, Search } from 'lucide-react';
import { listWorkouts } from '../../api';
import type { Workout } from '../../types';
import './styles.css';

const DATA_RESOURCES = new Set(['workouts', 'runs', 'view-state']);

type WidgetContext = {
  content?: {
    payload?: {
      active_app_params?: Record<string, unknown>;
      is_mobile_layout?: boolean;
    };
  };
};

function contextToken() {
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get('context') || new URLSearchParams(window.location.search).get('context') || '';
}

async function loadWidgetContext(): Promise<WidgetContext> {
  const token = contextToken();
  if (!token) return {};
  const response = await fetch(`/api/apps/widgets/context/${encodeURIComponent(token)}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) return {};
  return (await response.json()).context as WidgetContext;
}

function activeWorkoutFromContext(context: WidgetContext) {
  const appPage = String(context.content?.payload?.active_app_params?.app_page || '');
  if (appPage.startsWith('workouts/')) return appPage.split('/')[1] || '';
  return String(context.content?.payload?.active_app_params?.workout_id || '');
}

function isMobileFromContext(context: WidgetContext) {
  return context.content?.payload?.is_mobile_layout === true;
}

function openWorkout(workoutId: string, isMobile: boolean) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'fitness-coach',
      params: { app_page: `workouts/${workoutId}`, workout_id: workoutId }
    },
    window.location.origin
  );
  if (isMobile) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function Sidebar() {
  const [query, setQuery] = useState('');
  const [workouts, setWorkouts] = useState<Workout[]>([]);
  const [activeWorkoutId, setActiveWorkoutId] = useState('');
  const [isMobile, setIsMobile] = useState(false);
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async () => {
    try {
      setWorkouts(await listWorkouts(query));
      setNotice('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to load workouts.');
    }
  }, [query]);

  useEffect(() => {
    loadWidgetContext().then((context) => {
      setActiveWorkoutId(activeWorkoutFromContext(context));
      setIsMobile(isMobileFromContext(context));
    });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { context?: WidgetContext; owner_app_id?: string; resource?: string; selection?: Record<string, unknown>; type?: string };
      if (payload.type === 'maverick.widget.context-changed' && payload.context) {
        setActiveWorkoutId(activeWorkoutFromContext(payload.context));
        setIsMobile(isMobileFromContext(payload.context));
      }
      if (payload.type === 'maverick.app.selection-changed' && payload.owner_app_id === 'fitness-coach') {
        setActiveWorkoutId(String(payload.selection?.workout_id || ''));
      }
      if (payload.type === 'maverick.widget.data-changed' && payload.owner_app_id === 'fitness-coach' && DATA_RESOURCES.has(String(payload.resource || ''))) {
        refresh();
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [refresh]);

  const rows = useMemo(() => workouts, [workouts]);

  return (
    <main className={`fitness-sidebar-widget ${isMobile ? 'is-shell-mobile' : ''}`}>
      <label className="fitness-sidebar-search-frame">
        <Search size={15} aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search workouts" />
      </label>
      <div className="fitness-sidebar-list">
        {notice ? <div className="fitness-sidebar-empty">{notice}</div> : null}
        {!notice && rows.length === 0 ? <div className="fitness-sidebar-empty">No workouts</div> : null}
        {rows.map((workout) => {
          const isActive = activeWorkoutId === workout.id;
          return (
            <button
              type="button"
              key={workout.id}
              className={`fitness-sidebar-row ${isActive ? 'is-active' : ''}`}
              onClick={() => openWorkout(workout.id, isMobile)}
              aria-current={isActive ? 'page' : undefined}
            >
              <Dumbbell size={15} aria-hidden="true" />
              <span>{workout.name}</span>
              <small>{workout.blocks.filter((block) => block.type === 'work').length} exercises</small>
            </button>
          );
        })}
      </div>
    </main>
  );
}

createRoot(document.getElementById('fitness-coach-sidebar-root') as HTMLElement).render(<Sidebar />);
