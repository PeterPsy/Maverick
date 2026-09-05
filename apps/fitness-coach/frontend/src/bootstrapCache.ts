import { projectBootstrapReadModel } from './bootstrapProjection';
import type { AppBootstrapPayload } from './types';

export function purgeLegacyBootstrapCache(): void {
  // These keys never attested user scope. Delete the namespace, never import it.
  try {
    const storage = window.sessionStorage;
    const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index));
    for (const key of keys) if (key?.startsWith('fitness-coach:bootstrap:')) storage.removeItem(key);
  } catch { /* Optional cleanup cannot block current authenticated reads. */ }
}

export function sanitizeBootstrapReadModel(value: unknown): AppBootstrapPayload | null {
  return sanitizeBootstrap(value);
}

function sanitizeBootstrap(value: unknown): AppBootstrapPayload | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const payload = value as Partial<AppBootstrapPayload>;
  if (payload.schema !== 'fitness-coach.bootstrap.v1'
      || typeof payload.workspace_id !== 'string'
      || payload.workspace_id.length > 256
      || typeof payload.app_id !== 'string'
      || payload.app_id.length > 256
      || typeof payload.state_version !== 'string'
      || !payload.state_version
      || payload.state_version.length > 256
      || !Array.isArray(payload.workouts)
      || !Array.isArray(payload.workout_summaries)
      || !Array.isArray(payload.exercises)
      || !Array.isArray(payload.tags)
      || !Array.isArray(payload.runs)
      || !payload.view_state || typeof payload.view_state !== 'object'
      || !payload.workouts.every(hasBoundedId)
      || !payload.workout_summaries.every(hasBoundedId)
      || !payload.exercises.every(hasBoundedId)
      || !payload.runs.every(hasBoundedId)
      || !payload.tags.every((tag) => typeof tag === 'string')
      || (payload.selected_workout !== null && !hasBoundedId(payload.selected_workout))
      || !validViewState(payload.view_state)) return null;
  try {
    const sanitized = projectBootstrapReadModel(payload as AppBootstrapPayload);
    if (!sanitized) return null;
    sanitized.schema = 'fitness-coach.bootstrap.v1';
    delete sanitized.not_modified;
    return sanitized;
  } catch {
    return null;
  }
}

function hasBoundedId(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const id = (value as { id?: unknown }).id;
  return typeof id === 'string' && id.length > 0 && id.length <= 256;
}

function validViewState(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const state = value as { selected_workout_id?: unknown; setup_tab?: unknown; sidebar_query?: unknown };
  return (state.selected_workout_id === null || typeof state.selected_workout_id === 'string')
    && (state.setup_tab === 'workout-settings' || state.setup_tab === 'exercise-library')
    && typeof state.sidebar_query === 'string';
}
