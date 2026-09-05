import type { AppBootstrapPayload } from './types';

// Closed display schema. In particular media capabilities and arbitrary nested
// backend/provider objects are not promoted with the personal-data approval.
type Shape = { scalar: string[]; children?: Record<string, Shape>; lists?: Record<string, Shape> };
const media: Shape = { scalar: ['kind', 'provider', 'file_id', 'stable_storage_file_id', 'connection_id', 'drive_file_id', 'workspace_relative_path', 'display_path', 'name', 'content_type', 'preview_kind', 'size_bytes', 'sha256', 'etag_or_version', 'source_version'] };
const folder: Shape = { scalar: ['kind', 'role', 'provider', 'connection_id', 'drive_file_id', 'folder_relative_path', 'workspace_relative_path', 'display_path'] };
const block: Shape = { scalar: ['id', 'type', 'exercise_id', 'exercise_snapshot_updated_at', 'title', 'short_description', 'long_description', 'tags', 'mode', 'seconds', 'reps', 'reps_label', 'notes', 'show_next_exercise', 'skip_if_last'], children: { media } };
const workout: Shape = { scalar: ['id', 'name', 'default_work_seconds', 'default_rest_seconds', 'default_reps', 'created_at', 'updated_at', 'last_started_at', 'last_completed_at'], children: { media_folder: folder }, lists: { blocks: block } };
const summary: Shape = { scalar: ['id', 'name', 'work_block_count', 'estimated_seconds', 'updated_at', 'last_started_at', 'last_completed_at'] };
const exercise: Shape = { scalar: ['id', 'title', 'short_description', 'long_description', 'tags', 'source_display_path', 'created_at', 'updated_at'], children: { primary_media: media, source_folder: folder }, lists: { media } };
const run: Shape = { scalar: ['id', 'workout_id', 'workout_name', 'started_at', 'completed_at', 'elapsed_seconds', 'completed_segments', 'skipped_segments', 'exercise_count'] };
const bootstrap: Shape = { scalar: ['schema', 'workspace_id', 'app_id', 'state_version', 'tags'], children: { selected_workout: workout, view_state: { scalar: ['selected_workout_id', 'setup_tab', 'sidebar_query'] } }, lists: { workouts: workout, workout_summaries: summary, exercises: exercise, runs: run } };

function project(value: unknown, shape: Shape): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const result: Record<string, unknown> = {};
  for (const field of shape.scalar) {
    const item = raw[field];
    if (item === undefined) continue;
    if (Array.isArray(item)) {
      if (field !== 'tags' || !item.every((entry) => typeof entry === 'string')) return null;
      result[field] = [...item];
    } else if (item === null || typeof item === 'boolean' || (typeof item === 'number' && Number.isFinite(item)) || typeof item === 'string') {
      if (typeof item === 'string' && (/^blob\s*:/iu.test(item) || /[?&](?:sig|signature|x-amz-signature|x-goog-signature)=/iu.test(item))) continue;
      result[field] = item;
    } else return null;
  }
  for (const [field, child] of Object.entries(shape.children ?? {})) {
    if (raw[field] === undefined) continue;
    if (raw[field] === null) { result[field] = null; continue; }
    const next = project(raw[field], child);
    if (!next) return null;
    result[field] = next;
  }
  for (const [field, child] of Object.entries(shape.lists ?? {})) {
    if (!Array.isArray(raw[field])) return null;
    const items = raw[field].map((item) => project(item, child));
    if (items.some((item) => !item)) return null;
    result[field] = items;
  }
  return result;
}

export function projectBootstrapReadModel(value: AppBootstrapPayload): AppBootstrapPayload | null {
  return project(value, bootstrap) as AppBootstrapPayload | null;
}
