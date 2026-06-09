import { afterEach, describe, expect, it, vi } from 'vitest';
import { currentStorageAppId } from './api';
import { driveMediaStreamUrl } from './mediaPlaybackResolver';
import type { ExerciseMediaRef, WorkBlock, Workout } from './types';
import { runtimeSegmentsForWorkout } from './workoutSegments';
import { validateWorkoutForStart } from './workoutValidation';

const media: ExerciseMediaRef = {
  kind: 'local_file',
  provider: 'local',
  file_id: 'file_media',
  workspace_relative_path: 'storage/uploaded/workout/video.png',
  display_path: 'storage/uploaded/workout/video.png',
  name: 'video.png',
  content_type: 'image/png',
  preview_kind: 'image'
};

function workout(): Workout {
  return {
    id: 'workout_1',
    name: 'Test',
    media_folder: null,
    default_work_seconds: 40,
    default_rest_seconds: 20,
    default_reps: 12,
    created_at: '2026-06-09T00:00:00Z',
    updated_at: '2026-06-09T00:00:00Z',
    last_started_at: null,
    last_completed_at: null,
    blocks: [
      {
        id: 'work_1',
        type: 'work',
        exercise_id: null,
        exercise_snapshot_updated_at: null,
        title: 'Squat',
        short_description: 'Drive up.',
        long_description: 'Keep chest tall.',
        tags: ['legs'],
        mode: 'timer',
        seconds: 30,
        reps: null,
        reps_label: null,
        media,
        notes: null
      },
      {
        id: 'rest_1',
        type: 'rest',
        title: 'Recupero',
        short_description: 'Breathe.',
        long_description: 'Prepare.',
        seconds: 20,
        show_next_exercise: true,
        skip_if_last: true
      }
    ]
  };
}

describe('workout logic', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('validates start requirements', () => {
    expect(validateWorkoutForStart(workout()).valid).toBe(true);
    const invalid = workout();
    invalid.blocks[0] = { ...(invalid.blocks[0] as WorkBlock), media: null };
    const validation = validateWorkoutForStart(invalid);
    expect(validation.valid).toBe(false);
    expect(validation.errors.map((error) => error.path)).toContain('blocks[0].media');
  });

  it('skips final rest when configured', () => {
    const segments = runtimeSegmentsForWorkout(workout());
    expect(segments).toHaveLength(1);
    expect(segments[0].type).toBe('work');
  });

  it('builds Drive media stream URLs without raw Google URLs', () => {
    const driveMedia: Extract<ExerciseMediaRef, { kind: 'drive_file' }> = {
      kind: 'drive_file',
      provider: 'google_drive',
      stable_storage_file_id: 'file_drive',
      connection_id: 'drive_conn',
      drive_file_id: 'drive_file',
      display_path: 'Drive/clip.mp4',
      name: 'clip.mp4',
      content_type: 'video/mp4',
      preview_kind: 'video',
      source_version: 'etag-1'
    };
    const url = driveMediaStreamUrl(driveMedia, 'storage');
    expect(url).toContain('/api/apps/storage/media?');
    expect(url).toContain('stable_storage_file_id=file_drive');
    expect(url).not.toContain('drive.google.com');
  });

  it('keeps Storage as the media owner when Fitness Coach is mounted', () => {
    vi.stubGlobal('window', { location: { pathname: '/apps/fitness-coach/', search: '' } });
    expect(currentStorageAppId()).toBe('storage');
  });
});
