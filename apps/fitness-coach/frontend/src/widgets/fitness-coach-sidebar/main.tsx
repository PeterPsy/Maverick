import { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Dumbbell, Library, Search, Timer } from 'lucide-react';
import { listWorkouts, updateViewState } from '../../api';
import type { SetupTab, Workout } from '../../types';
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

function setupTabFromContext(context: WidgetContext): SetupTab {
  const setupTab = String(context.content?.payload?.active_app_params?.setup_tab || '');
  return setupTab === 'exercise-library' ? 'exercise-library' : 'workout-settings';
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

function openSetupTab(setupTab: SetupTab, isMobile: boolean) {
  updateViewState({ setup_tab: setupTab }).catch(() => undefined);
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'fitness-coach',
      params: { setup_tab: setupTab }
    },
    window.location.origin
  );
  if (isMobile) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function Sidebar() {
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [workouts, setWorkouts] = useState<Workout[]>([]);
  const [activeWorkoutId, setActiveWorkoutId] = useState('');
  const [setupTab, setSetupTab] = useState<SetupTab>('workout-settings');
  const [isMobile, setIsMobile] = useState(false);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async () => {
    try {
      setWorkouts(await listWorkouts(debouncedQuery));
      setNotice('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to load workouts.');
    } finally {
      setIsInitialLoading(false);
    }
  }, [debouncedQuery]);

  useEffect(() => {
    loadWidgetContext().then((context) => {
      setActiveWorkoutId(activeWorkoutFromContext(context));
      setSetupTab(setupTabFromContext(context));
      setIsMobile(isMobileFromContext(context));
    });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { context?: WidgetContext; owner_app_id?: string; resource?: string; selection?: Record<string, unknown>; type?: string };
      if (payload.type === 'maverick.widget.context-changed' && payload.context) {
        setActiveWorkoutId(activeWorkoutFromContext(payload.context));
        setSetupTab(setupTabFromContext(payload.context));
        setIsMobile(isMobileFromContext(payload.context));
      }
      if (payload.type === 'maverick.app.selection-changed' && payload.owner_app_id === 'fitness-coach') {
        setActiveWorkoutId(String(payload.selection?.workout_id || ''));
        const nextSetupTab = String(payload.selection?.setup_tab || '');
        if (nextSetupTab === 'workout-settings' || nextSetupTab === 'exercise-library') {
          setSetupTab(nextSetupTab);
        }
      }
      if (payload.type === 'maverick.widget.data-changed' && payload.owner_app_id === 'fitness-coach' && DATA_RESOURCES.has(String(payload.resource || ''))) {
        refresh();
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [refresh]);

  const rows = useMemo(() => workouts, [workouts]);
  function handleSetupTab(nextSetupTab: SetupTab) {
    setSetupTab(nextSetupTab);
    openSetupTab(nextSetupTab, isMobile);
  }

  return (
    <main className={`fitness-sidebar-widget ${isMobile ? 'is-shell-mobile' : ''}`}>
      <div className="fitness-sidebar-switch" role="tablist" aria-label="Setup mode">
        <button type="button" className={setupTab === 'workout-settings' ? 'is-active' : ''} onClick={() => handleSetupTab('workout-settings')}>
          <Timer size={14} aria-hidden="true" />
          <span>Workout</span>
        </button>
        <button type="button" className={setupTab === 'exercise-library' ? 'is-active' : ''} onClick={() => handleSetupTab('exercise-library')}>
          <Library size={14} aria-hidden="true" />
          <span>Library</span>
        </button>
      </div>
      <label className="fitness-sidebar-search-frame">
        <Search size={15} aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search workouts" />
      </label>
      <div className="fitness-sidebar-list">
        {isInitialLoading ? <FitnessSidebarSkeleton /> : null}
        {!isInitialLoading && notice ? <div className="fitness-sidebar-empty">{notice}</div> : null}
        {!isInitialLoading && !notice && rows.length === 0 ? <div className="fitness-sidebar-empty">No workouts</div> : null}
        {!isInitialLoading && rows.map((workout) => {
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

function FitnessSidebarSkeleton() {
  return (
    <div aria-hidden="true" className="fitness-sidebar-skeleton">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="fitness-sidebar-skeleton__row" key={index}>
          <span className="fitness-sidebar-skeleton__icon" />
          <span className="fitness-sidebar-skeleton__copy">
            <span />
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('fitness-coach-sidebar-root') as HTMLElement).render(<Sidebar />);
