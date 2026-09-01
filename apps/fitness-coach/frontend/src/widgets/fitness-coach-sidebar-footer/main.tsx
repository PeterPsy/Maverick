import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Dumbbell, Plus } from 'lucide-react';
import './styles.css';

const APP_ID = 'fitness-coach';
const WIDGET_ID = 'fitness-coach-sidebar-footer';
const PRIMARY_ACTION_LABEL = 'New workout';

function postPrimaryActionState(available: boolean) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.primary-action.state',
      owner_app_id: APP_ID,
      widget_id: WIDGET_ID,
      available,
      label: PRIMARY_ACTION_LABEL,
      preferred_surface: 'sidebar'
    },
    "*"
  );
}

function openApp(params: Record<string, unknown>) {
  window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: APP_ID, params }, "*");
}

function Footer() {
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    postPrimaryActionState(!busy);
  }, [busy]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { owner_app_id?: string; type?: string; widget_id?: string };
      if (payload.owner_app_id !== APP_ID || payload.widget_id !== WIDGET_ID) return;
      if (payload.type === 'maverick.widget.primary-action.query') {
        postPrimaryActionState(!busy);
      }
      if (payload.type === 'maverick.widget.primary-action.invoke' && !busy) {
        newWorkout();
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [busy]);

  function newWorkout() {
    setBusy(true);
    openApp({ new_workout: true, new_workout_request_id: crypto.randomUUID() });
    window.setTimeout(() => setBusy(false), 250);
  }

  function newExercise() {
    setBusy(true);
    openApp({ new_exercise: true, new_exercise_request_id: crypto.randomUUID(), setup_tab: 'exercise-library' });
    window.setTimeout(() => setBusy(false), 250);
  }

  return (
    <main className="fitness-sidebar-footer-widget">
      <button className="fitness-footer-primary" type="button" onClick={newWorkout} disabled={busy}>
        <Plus size={16} aria-hidden="true" />
        <span>New workout</span>
      </button>
      <button className="fitness-footer-secondary" type="button" onClick={newExercise} disabled={busy}>
        <Dumbbell size={16} aria-hidden="true" />
        <span>New exercise</span>
      </button>
    </main>
  );
}

createRoot(document.getElementById('fitness-coach-sidebar-footer-root') as HTMLElement).render(<Footer />);
