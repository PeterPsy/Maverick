import { describe, expect, it, vi } from 'vitest';
import { completeWorkoutAfterConfirmedStart } from './workoutCompletion';
import type { StartWorkoutPayload, WorkoutRunSummary } from './types';

function deferredStart() {
  let resolve!: (payload: StartWorkoutPayload) => void;
  const promise = new Promise<StartWorkoutPayload>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe('workout completion', () => {
  it('waits for confirmed start before completing the workout', async () => {
    const start = deferredStart();
    const run = { id: 'run_1' } as WorkoutRunSummary;
    const completeWorkout = vi.fn(async () => run);
    const completion = completeWorkoutAfterConfirmedStart({
      startPromise: start.promise,
      completeWorkout,
      workoutId: 'workout_1',
      startedAt: '2026-06-10T10:00:00.000Z',
      completedSegments: 3,
      skippedSegments: 1,
      exerciseCount: 2,
      now: () => Date.parse('2026-06-10T10:00:08.000Z')
    });

    await Promise.resolve();
    expect(completeWorkout).not.toHaveBeenCalled();

    start.resolve({
      workout: { id: 'workout_1' } as StartWorkoutPayload['workout'],
      validation: { valid: true, errors: [], work_block_count: 2, estimated_seconds: 8 },
      started_at: '2026-06-10T10:00:02.000Z'
    });

    await expect(completion).resolves.toBe(run);
    expect(completeWorkout).toHaveBeenCalledWith({
      workout_id: 'workout_1',
      started_at: '2026-06-10T10:00:00.000Z',
      elapsed_seconds: 8,
      completed_segments: 3,
      skipped_segments: 1,
      exercise_count: 2
    });
  });
});
