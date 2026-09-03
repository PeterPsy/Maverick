import type { AppBootstrapPayload, Exercise, ExerciseMediaRef, StartWorkoutPayload, StorageFile, StorageFolderRef, ViewState, Workout, WorkoutRunSummary, WorkoutValidation } from './types';

export type BackendListPayload = {
  workouts?: Workout[];
  exercises?: Exercise[];
  runs?: WorkoutRunSummary[];
  view_state?: ViewState;
};

const EMPTY_STORAGE_SECRET_REQUEST = {
  logical_names: [],
  required: false
};

const UPLOAD_BUCKET_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function callBackend<T>(body: Record<string, unknown>, options: { signal?: AbortSignal } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch('/api/apps/fitness-coach/backend', {
      method: 'POST',
      credentials: 'same-origin',
      signal: options.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    const transport = new Error('Fitness Coach backend transport failed.', { cause: error });
    transport.name = 'MaverickTransportError';
    throw transport;
  }
  let payload: T & { error?: string; detail?: string };
  try {
    payload = (await response.json()) as T & { error?: string; detail?: string };
  } catch (error) {
    if (response.ok) throw new TypeError('Fitness Coach returned an invalid JSON response.', { cause: error });
    payload = {} as T & { error?: string; detail?: string };
  }
  if (!response.ok) {
    throw new FitnessHttpError(
      payload.detail || payload.error || `Backend request failed with ${response.status}`,
      response.status,
      parseRetryAfter(response.headers.get('retry-after'))
    );
  }
  return payload;
}

export class FitnessHttpError extends Error {
  constructor(message: string, readonly status: number, readonly retryAfterMs: number | null) {
    super(message);
    this.name = 'MaverickHttpError';
  }
}

export async function listWorkouts(query = '') {
  const payload = await callBackend<{ workouts: Workout[] }>({ action: 'workouts.list', query });
  return payload.workouts;
}

export async function bootstrapApp(options: { includeRuns?: boolean; selectedWorkoutId?: string | null } = {}) {
  const payload = await callBackend<AppBootstrapPayload>({
    action: 'app.bootstrap',
    include_runs: options.includeRuns === true,
    selected_workout_id: options.selectedWorkoutId || ''
  });
  return payload;
}

export async function getWorkout(workoutId: string) {
  const payload = await callBackend<{ workout: Workout }>({ action: 'workout.get', workout_id: workoutId });
  return payload.workout;
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

export async function startWorkout(workoutId: string, workout?: Workout) {
  const payload = await callBackend<StartWorkoutPayload>({ action: 'workout.start', workout_id: workoutId, workout });
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

export async function callStorageBackend<T>(body: Record<string, unknown>, storageAppId = currentStorageAppId(), options: { signal?: AbortSignal } = {}): Promise<T> {
  const response = await fetch(`/api/apps/${encodeURIComponent(storageAppId)}/backend`, {
    method: 'POST',
    credentials: 'same-origin',
    signal: options.signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(withDefaultStorageSecretRequest(body))
  });
  const payload = (await response.json()) as T & { error?: string; detail?: string };
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Storage request failed with ${response.status}`);
  }
  return payload;
}

export type StorageMediaPickerSelection = {
  media: ExerciseMediaRef;
  sourceDisplayPath: string | null;
  sourceFolder: StorageFolderRef | null;
};

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

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1_000, 60_000);
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? Math.max(0, Math.min(timestamp - Date.now(), 60_000)) : null;
}

export function openStorageForMedia(media: ExerciseMediaRef | null, sourceFolder?: StorageFolderRef | null) {
  const params = storageNavigationParamsForMedia(media, sourceFolder);
  window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: 'storage', params }, "*");
}

export function openStorageVideoPicker(media: ExerciseMediaRef | null, sourceFolder?: StorageFolderRef | null) {
  const params = storageVideoPickerNavigationParamsForMedia(media, sourceFolder);
  window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: 'storage', params }, "*");
}

export function storageVideoPickerNavigationParamsForMedia(media: ExerciseMediaRef | null, sourceFolder?: StorageFolderRef | null): Record<string, string> {
  return {
    ...storageNavigationParamsForMedia(media, sourceFolder),
    picker_accept: 'video',
    picker_mode: 'fitness-coach-media',
    picker_return_app_id: 'fitness-coach'
  };
}

export function storageNavigationParamsForMedia(media: ExerciseMediaRef | null, sourceFolder?: StorageFolderRef | null): Record<string, string> {
  if (!media) {
    return sourceFolder ? storageNavigationParamsForFolder(sourceFolder) : {};
  }
  if (media.kind === 'local_file') {
    const folder = localStorageFolderParams(media.workspace_relative_path);
    if (folder) return folder;
    return media.file_id ? { file_id: media.file_id } : {};
  }
  if (sourceFolder?.kind === 'drive_folder' && driveFolderContainsMedia(sourceFolder, media)) {
    return {
      provider: 'google_drive',
      connection_id: sourceFolder.connection_id,
      drive_file_id: sourceFolder.drive_file_id,
      display_path: sourceFolder.display_path
    };
  }
  const fileId = media.stable_storage_file_id.trim();
  return fileId ? { file_id: fileId, app_page: `files/${encodeURIComponent(fileId)}` } : {};
}

export function storageMediaSelectionFromPickerParams(params: Record<string, unknown>): StorageMediaPickerSelection | null {
  if (String(params.picker_mode || '') !== 'fitness-coach-media') {
    return null;
  }
  const rawResult = params.storage_picker_result;
  const result = typeof rawResult === 'string' ? parseJsonObject(rawResult) : rawResult;
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    return null;
  }
  const file = (result as { file?: unknown }).file;
  if (!file || typeof file !== 'object' || Array.isArray(file)) {
    return null;
  }
  const media = storageFileToMediaRef(file as StorageFile);
  if (!media || media.preview_kind !== 'video') {
    return null;
  }
  const sourceFolder = storageFolderRefFromUnknown((result as { source_folder?: unknown }).source_folder);
  const sourceDisplayPath = stringOrNull((result as { source_display_path?: unknown }).source_display_path) || sourceFolder?.display_path || null;
  return { media, sourceDisplayPath, sourceFolder };
}

function withDefaultStorageSecretRequest(body: Record<string, unknown>) {
  const request = body._app_secret_request;
  if (request && typeof request === 'object' && !Array.isArray(request)) {
    return body;
  }
  return { ...body, _app_secret_request: EMPTY_STORAGE_SECRET_REQUEST };
}

function localStorageFolderParams(workspaceRelativePath: string) {
  const match = /^storage\/(uploaded|generated)\/(.+)$/.exec(workspaceRelativePath.trim());
  if (!match) return null;
  const pathParts = match[2].split('/').filter(Boolean);
  const folderParts = match[1] === 'uploaded' && pathParts.length === 2 && UPLOAD_BUCKET_PATTERN.test(pathParts[0])
    ? []
    : pathParts.slice(0, -1);
  return {
    role: match[1],
    folder_relative_path: folderParts.join('/')
  };
}

function storageNavigationParamsForFolder(sourceFolder: StorageFolderRef): Record<string, string> {
  if (sourceFolder.kind === 'drive_folder') {
    return {
      provider: 'google_drive',
      connection_id: sourceFolder.connection_id,
      drive_file_id: sourceFolder.drive_file_id,
      display_path: sourceFolder.display_path
    };
  }
  return {
    role: sourceFolder.role,
    folder_relative_path: sourceFolder.folder_relative_path
  };
}

function driveFolderContainsMedia(folder: Extract<StorageFolderRef, { kind: 'drive_folder' }>, media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>) {
  if (!folder.connection_id || folder.connection_id !== media.connection_id || !folder.drive_file_id) {
    return false;
  }
  const folderPath = folder.display_path.replace(/\/+$/, '');
  const mediaPath = media.display_path.trim();
  if (!folderPath || !mediaPath) {
    return false;
  }
  return mediaPath === folderPath || mediaPath.startsWith(`${folderPath}/`);
}

function parseJsonObject(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function storageFolderRefFromUnknown(value: unknown): StorageFolderRef | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  const folder = value as Record<string, unknown>;
  if (folder.kind === 'drive_folder') {
    const connectionId = stringOrNull(folder.connection_id);
    const driveFileId = stringOrNull(folder.drive_file_id);
    const displayPath = stringOrNull(folder.display_path);
    if (!connectionId || !driveFileId || !displayPath) {
      return null;
    }
    return {
      kind: 'drive_folder',
      provider: 'google_drive',
      connection_id: connectionId,
      drive_file_id: driveFileId,
      display_path: displayPath
    };
  }
  if (folder.kind === 'local_folder') {
    const role = folder.role === 'uploaded' || folder.role === 'generated' ? folder.role : null;
    const folderRelativePath = stringOrNull(folder.folder_relative_path) || '';
    const workspaceRelativePath = stringOrNull(folder.workspace_relative_path) || (role ? `storage/${role}${folderRelativePath ? `/${folderRelativePath}` : ''}` : '');
    if (!role || !workspaceRelativePath.startsWith(`storage/${role}`)) {
      return null;
    }
    return {
      kind: 'local_folder',
      role,
      folder_relative_path: folderRelativePath,
      workspace_relative_path: workspaceRelativePath,
      display_path: stringOrNull(folder.display_path) || workspaceRelativePath
    };
  }
  return null;
}

function stringOrNull(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
