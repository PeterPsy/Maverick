export type SetupTab = 'workout-settings' | 'exercise-library';

export type StorageFolderRef =
  | {
      kind: 'local_folder';
      role: 'uploaded' | 'generated';
      folder_relative_path: string;
      workspace_relative_path: string;
      display_path: string;
    }
  | {
      kind: 'drive_folder';
      provider: 'google_drive';
      connection_id: string;
      drive_file_id: string;
      display_path: string;
    };

export type ExerciseMediaRef =
  | {
      kind: 'local_file';
      provider: 'local';
      file_id: string;
      workspace_relative_path: string;
      display_path: string;
      name: string;
      content_type: string;
      preview_kind: 'video' | 'image';
      size_bytes?: number | null;
      sha256?: string | null;
      etag_or_version?: string | null;
      capabilities?: { can_read?: boolean; can_preview?: boolean };
    }
  | {
      kind: 'drive_file';
      provider: 'google_drive';
      stable_storage_file_id: string;
      connection_id: string;
      drive_file_id: string;
      display_path: string;
      name: string;
      content_type: string;
      preview_kind: 'video' | 'image';
      size_bytes?: number | null;
      source_version?: string | null;
      etag_or_version?: string | null;
      capabilities?: { can_read?: boolean; can_preview?: boolean };
    };

export type WorkBlock = {
  id: string;
  type: 'work';
  exercise_id: string | null;
  exercise_snapshot_updated_at: string | null;
  title: string;
  short_description: string;
  long_description: string;
  tags: string[];
  mode: 'timer' | 'reps';
  seconds: number | null;
  reps: number | null;
  reps_label: string | null;
  media: ExerciseMediaRef | null;
  notes: string | null;
};

export type RestBlock = {
  id: string;
  type: 'rest';
  title: string;
  short_description: string;
  long_description: string;
  seconds: number;
  show_next_exercise: boolean;
  skip_if_last: boolean;
};

export type WorkoutBlock = WorkBlock | RestBlock;

export type Workout = {
  id: string;
  name: string;
  media_folder: StorageFolderRef | null;
  default_work_seconds: number;
  default_rest_seconds: number;
  default_reps: number;
  blocks: WorkoutBlock[];
  created_at: string;
  updated_at: string;
  last_started_at: string | null;
  last_completed_at: string | null;
};

export type WorkoutSummary = {
  id: string;
  name: string;
  work_block_count: number;
  estimated_seconds: number;
  updated_at: string;
  last_started_at: string | null;
  last_completed_at: string | null;
};

export type Exercise = {
  id: string;
  title: string;
  short_description: string;
  long_description: string;
  tags: string[];
  primary_media: ExerciseMediaRef | null;
  media: ExerciseMediaRef[];
  source_folder: StorageFolderRef | null;
  source_display_path: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkoutRunSummary = {
  id: string;
  workout_id: string;
  workout_name: string;
  started_at: string;
  completed_at: string;
  elapsed_seconds: number;
  completed_segments: number;
  skipped_segments: number;
  exercise_count: number;
};

export type ViewState = {
  selected_workout_id: string | null;
  setup_tab: SetupTab;
  sidebar_query: string;
};

export type AppBootstrapPayload = {
  schema?: 'fitness-coach.bootstrap.v1';
  not_modified?: boolean;
  workspace_id: string;
  app_id: string;
  state_version: string;
  workouts: Workout[];
  workout_summaries: WorkoutSummary[];
  selected_workout: Workout | null;
  exercises: Exercise[];
  tags: string[];
  runs: WorkoutRunSummary[];
  view_state: ViewState;
};

export type StartWorkoutPayload = {
  workout: Workout;
  validation: WorkoutValidation;
  started_at: string;
};

export type ValidationIssue = {
  path: string;
  message: string;
};

export type WorkoutValidation = {
  valid: boolean;
  errors: ValidationIssue[];
  work_block_count: number;
  estimated_seconds: number;
};

export type RuntimeSegment =
  | {
      type: 'work';
      blockId: string;
      mode: 'timer' | 'reps';
      media: ExerciseMediaRef;
      title: string;
      short_description: string;
      long_description: string;
      seconds?: number;
      reps?: number;
      repsLabel?: string;
    }
  | {
      type: 'rest';
      blockId: string;
      phase?: 'preparation';
      title: string;
      short_description: string;
      long_description: string;
      seconds: number;
      nextWorkSegmentId: string | null;
      showNextExercise: boolean;
    };

export type StorageFile = {
  id?: string;
  file_id?: string;
  stable_storage_file_id?: string;
  provider?: string;
  connection_id?: string;
  drive_file_id?: string;
  role?: 'uploaded' | 'generated';
  name?: string;
  display_path?: string;
  relative_path?: string;
  workspace_relative_path?: string;
  content_type?: string;
  preview_kind?: string;
  size_bytes?: number;
  sha256?: string;
  etag_or_version?: string;
  source_version?: string;
  capabilities?: { can_read?: boolean; can_preview?: boolean };
};

export type MediaResolverStatus = 'idle' | 'resolving' | 'localizing' | 'ready' | 'blocked' | 'error';

export type MediaPlaybackResolution = {
  status: MediaResolverStatus;
  url: string;
  mediaKind: 'video' | 'image' | 'none';
  detail: string;
  canRetry?: boolean;
  canCancel?: boolean;
  revoke?: () => void;
  warmup?: Promise<MediaPlaybackResolution | null>;
};
