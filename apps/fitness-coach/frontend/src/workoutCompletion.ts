import type { StartWorkoutPayload, WorkoutRunSummary } from './types';

type CompleteWorkoutAfterStartInput = {
  startPromise: Promise<StartWorkoutPayload>;
  completeWorkout: (summary: Record<string, unknown>) => Promise<WorkoutRunSummary>;
  workoutId: string;
  startedAt: string;
  completedSegments: number;
  skippedSegments: number;
  exerciseCount: number;
  now?: () => number;
};

export async function completeWorkoutAfterConfirmedStart({
  startPromise,
  completeWorkout,
  workoutId,
  startedAt,
  completedSegments,
  skippedSegments,
  exerciseCount,
  now = Date.now
}: CompleteWorkoutAfterStartInput) {
  await startPromise;
  const runStartedAt = startedAt;
  const startedAtMs = Date.parse(startedAt);
  const elapsed_seconds = Number.isFinite(startedAtMs)
    ? Math.max(0, Math.round((now() - startedAtMs) / 1000))
    : 0;
  return completeWorkout({
    workout_id: workoutId,
    started_at: runStartedAt,
    elapsed_seconds,
    completed_segments: completedSegments,
    skipped_segments: skippedSegments,
    exercise_count: exerciseCount
  });
}
