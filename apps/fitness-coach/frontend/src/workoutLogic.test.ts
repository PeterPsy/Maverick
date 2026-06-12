import { afterEach, describe, expect, it, vi } from 'vitest';
import { currentStorageAppId } from './api';
import { driveMediaStreamUrl } from './mediaPlaybackResolver';
import type { ExerciseMediaRef, RestBlock, WorkBlock, Workout } from './types';
import { PREPARATION_BLOCK_SECONDS, repsLabel, runtimeSegmentsForWorkout, segmentProgressRepeats, segmentProgressSeconds } from './workoutSegments';
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
        exercise_id: 'exercise_1',
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
        title: 'Rest',
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
    const validation = validateWorkoutForStart(workout());
    expect(validation.valid).toBe(true);
    expect(validation.estimated_seconds).toBe(45);
    const invalid = workout();
    invalid.blocks[0] = { ...(invalid.blocks[0] as WorkBlock), media: null };
    const invalidValidation = validateWorkoutForStart(invalid);
    expect(invalidValidation.valid).toBe(false);
    expect(invalidValidation.errors.map((error) => error.path)).toContain('blocks[0].media');
  });

  it('prepends a fixed preparation segment and skips final rest when configured', () => {
    const segments = runtimeSegmentsForWorkout(workout());
    expect(segments).toHaveLength(2);
    expect(segments[0]).toMatchObject({
      type: 'rest',
      phase: 'preparation',
      title: 'Preparation',
      seconds: PREPARATION_BLOCK_SECONDS,
      showNextExercise: true
    });
    expect(segments[1].type).toBe('work');
  });

  it('uses timer seconds for timed progress and loops reps progress every minute', () => {
    const timedSegments = runtimeSegmentsForWorkout(workout());
    expect(segmentProgressSeconds(timedSegments[0])).toBe(PREPARATION_BLOCK_SECONDS);
    expect(segmentProgressRepeats(timedSegments[0])).toBe(false);
    expect(segmentProgressSeconds(timedSegments[1])).toBe(30);
    expect(segmentProgressRepeats(timedSegments[1])).toBe(false);

    const repsWorkout = workout();
    repsWorkout.blocks[0] = {
      ...(repsWorkout.blocks[0] as WorkBlock),
      mode: 'reps',
      seconds: null,
      reps: 12
    };
    repsWorkout.blocks[1] = { ...(repsWorkout.blocks[1] as RestBlock), skip_if_last: false };
    const repsSegments = runtimeSegmentsForWorkout(repsWorkout);

    expect(segmentProgressSeconds(repsSegments[1])).toBe(60);
    expect(segmentProgressRepeats(repsSegments[1])).toBe(true);
    expect(repsSegments[1].type === 'work' ? repsSegments[1].reps : null).toBe(12);
    expect(segmentProgressSeconds(repsSegments[2])).toBe(20);
    expect(segmentProgressRepeats(repsSegments[2])).toBe(false);
  });

  it('formats numeric reps labels with a visible reps unit', () => {
    const block = {
      ...(workout().blocks[0] as WorkBlock),
      mode: 'reps',
      seconds: null,
      reps: 20
    } satisfies WorkBlock;

    expect(repsLabel({ ...block, reps_label: null })).toBe('20 reps');
    expect(repsLabel({ ...block, reps_label: '20' })).toBe('20 reps');
    expect(repsLabel({ ...block, reps_label: '20 each side' })).toBe('20 each side');
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
