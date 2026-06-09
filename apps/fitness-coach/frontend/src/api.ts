import type { Exercise, ExerciseMediaRef, StorageFile, ViewState, Workout, WorkoutRunSummary, WorkoutValidation } from './types';

export type BackendListPayload = {
  workouts?: Workout[];
  exercises?: Exercise[];
  runs?: WorkoutRunSummary[];
  view_state?: ViewState;
};

export async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/fitness-coach/backend', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = (await response.json()) as T & { error?: string; detail?: string };
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Backend request failed with ${response.status}`);
  }
  return payload;
}

export async function listWorkouts(query = '') {
  const payload = await callBackend<{ workouts: Workout[] }>({ action: 'workouts.list', query });
  return payload.workouts;
}

export async function listExercises(query = '', tag = '') {
  const payload = await callBackend<{ exercises: Exercise[] }>({ action: 'exercises.list', query, tag });
  return payload.exercises;
}

export async function listRuns(workoutId?: string) {
  const payload = await callBackend<{ runs: WorkoutRunSummary[] }>({ action: 'runs.list', workout_id: workoutId || '', limit: 20 });
  return payload.runs;
}

export async function createWorkout(name = 'New workout') {
  const payload = await callBackend<{ workout: Workout }>({ action: 'workout.create', name });
  return payload.workout;
}

export async function saveWorkout(workout: Workout) {
  const payload = await callBackend<{ workout: Workout }>({ action: 'workout.update', workout });
  return payload.workout;
}

export async function duplicateWorkout(workoutId: string) {
  const payload = await callBackend<{ workout: Workout }>({ action: 'workout.duplicate', workout_id: workoutId });
  return payload.workout;
}

export async function deleteWorkout(workoutId: string) {
  await callBackend({ action: 'workout.delete', workout_id: workoutId });
}

export async function validateWorkout(workoutId: string) {
  const payload = await callBackend<{ validation: WorkoutValidation }>({ action: 'workout.validate', workout_id: workoutId });
  return payload.validation;
}

export async function startWorkout(workoutId: string) {
  const payload = await callBackend<{ workout: Workout; validation: WorkoutValidation; started_at: string }>({ action: 'workout.start', workout_id: workoutId });
  return payload;
}

export async function completeWorkout(summary: Record<string, unknown>) {
  const payload = await callBackend<{ run: WorkoutRunSummary }>({ action: 'workout.complete', ...summary });
  return payload.run;
}

export async function createExercise(exercise: Partial<Exercise>) {
  const payload = await callBackend<{ exercise: Exercise }>({ action: 'exercise.create', exercise });
  return payload.exercise;
}

export async function saveExercise(exercise: Exercise) {
  const payload = await callBackend<{ exercise: Exercise }>({ action: 'exercise.update', exercise });
  return payload.exercise;
}

export async function deleteExercise(exerciseId: string) {
  await callBackend({ action: 'exercise.delete', exercise_id: exerciseId });
}

export async function updateViewState(viewState: Partial<ViewState>) {
  const payload = await callBackend<{ view_state: ViewState }>({ action: 'view_state.update', ...viewState });
  return payload.view_state;
}

export async function callStorageBackend<T>(body: Record<string, unknown>, storageAppId = currentStorageAppId()): Promise<T> {
  const response = await fetch(`/api/apps/${encodeURIComponent(storageAppId)}/backend`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = (await response.json()) as T & { error?: string; detail?: string };
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Storage request failed with ${response.status}`);
  }
  return payload;
}

export async function listStorageMedia(query = '') {
  const payload = await callStorageBackend<{ files: StorageFile[] }>({
    action: 'catalog',
    role: 'all',
    kind: 'all',
    query,
    limit: 80
  });
  return (payload.files || []).filter((file) => file.preview_kind === 'image' || file.preview_kind === 'video');
}

export function storageFileToMediaRef(file: StorageFile): ExerciseMediaRef | null {
  const previewKind = file.preview_kind === 'video' ? 'video' : file.preview_kind === 'image' ? 'image' : '';
  if (!previewKind) return null;
  if (file.provider === 'google_drive') {
    return {
      kind: 'drive_file',
      provider: 'google_drive',
      stable_storage_file_id: String(file.stable_storage_file_id || file.file_id || file.id || ''),
      connection_id: String(file.connection_id || ''),
      drive_file_id: String(file.drive_file_id || ''),
      display_path: String(file.display_path || ''),
      name: String(file.name || 'Drive media'),
      content_type: String(file.content_type || ''),
      preview_kind: previewKind,
      size_bytes: file.size_bytes,
      source_version: file.source_version || file.etag_or_version || '',
      etag_or_version: file.etag_or_version || '',
      capabilities: file.capabilities || {}
    };
  }
  return {
    kind: 'local_file',
    provider: 'local',
    file_id: String(file.file_id || file.id || ''),
    workspace_relative_path: String(file.workspace_relative_path || ''),
    display_path: String(file.display_path || file.workspace_relative_path || ''),
    name: String(file.name || 'Storage media'),
    content_type: String(file.content_type || ''),
    preview_kind: previewKind,
    size_bytes: file.size_bytes,
    sha256: file.sha256 || '',
    etag_or_version: file.etag_or_version || '',
    capabilities: file.capabilities || {}
  };
}

export function currentStorageAppId() {
  const params = new URLSearchParams(typeof window === 'undefined' ? '' : window.location.search);
  return params.get('storage_app_id') || 'storage';
}

export function mountedAppIdFromPath(pathname: string, fallback: string): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) return fallback;
  try {
    return decodeURIComponent(match[1]) || fallback;
  } catch {
    return match[1] || fallback;
  }
}

export function openStorageForMedia(media: ExerciseMediaRef | null) {
  if (!media) {
    window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: 'storage', params: {} }, window.location.origin);
    return;
  }
  const params =
    media.kind === 'local_file'
      ? { file_id: media.file_id }
      : { provider: 'google_drive', connection_id: media.connection_id, drive_file_id: media.drive_file_id, display_path: media.display_path };
  window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: 'storage', params }, window.location.origin);
}
