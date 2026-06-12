import type { ExerciseMediaRef, Workout, WorkoutValidation } from './types';
import { PREPARATION_BLOCK_SECONDS } from './workoutSegments';

export function validateWorkoutForStart(workout: Workout | null): WorkoutValidation {
  const errors: WorkoutValidation['errors'] = [];
  if (!workout) {
    return { valid: false, errors: [{ path: 'workout', message: 'Select or create a workout.' }], work_block_count: 0, estimated_seconds: 0 };
  }
  const workBlocks = workout.blocks.filter((block) => block.type === 'work');
  if (workBlocks.length === 0) {
    errors.push({ path: 'blocks', message: 'Add at least one work block.' });
  }
  workout.blocks.forEach((block, index) => {
    const path = `blocks[${index}]`;
    if (block.type === 'rest') {
      if (block.seconds <= 0) errors.push({ path: `${path}.seconds`, message: 'Rest needs seconds > 0.' });
      return;
    }
    if (!block.exercise_id) errors.push({ path: `${path}.exercise_id`, message: 'Choose an exercise from the library.' });
    if (!block.title.trim()) errors.push({ path: `${path}.title`, message: 'Title is required.' });
    if (!(block.long_description.trim() || block.short_description.trim())) {
      errors.push({ path: `${path}.long_description`, message: 'Description is required.' });
    }
    if (block.mode === 'timer' && (!block.seconds || block.seconds <= 0)) {
      errors.push({ path: `${path}.seconds`, message: 'Timer blocks need seconds > 0.' });
    }
    if (block.mode === 'reps' && (!block.reps || block.reps <= 0) && !block.reps_label?.trim()) {
      errors.push({ path: `${path}.reps`, message: 'Reps blocks need reps > 0 or a reps label.' });
    }
    const mediaIssue = mediaPlaybackIssue(block.media);
    if (mediaIssue) errors.push({ path: `${path}.media`, message: mediaIssue });
  });
  return {
    valid: errors.length === 0,
    errors,
    work_block_count: workBlocks.length,
    estimated_seconds: estimateWorkoutSeconds(workout)
  };
}

export function mediaPlaybackIssue(media: ExerciseMediaRef | null): string {
  if (!media) return 'Attach a Storage image or video.';
  if (media.preview_kind !== 'image' && media.preview_kind !== 'video') return 'Only image or video media can be played.';
  if (media.kind === 'local_file') {
    if (!media.file_id || !media.workspace_relative_path.startsWith('storage/')) return 'Local media needs a stable Storage file id.';
    return '';
  }
  if (!media.stable_storage_file_id || !media.connection_id || !media.drive_file_id) {
    return 'Drive media needs stable Storage id, connection id, and Drive file id.';
  }
  return '';
}

export function estimateWorkoutSeconds(workout: Workout): number {
  const hasWork = workout.blocks.some((block) => block.type === 'work');
  const workoutSeconds = workout.blocks.reduce((total, block, index) => {
    if (block.type === 'rest') {
      const hasNextWork = workout.blocks.slice(index + 1).some((candidate) => candidate.type === 'work');
      if (block.skip_if_last && !hasNextWork) return total;
      return total + Math.max(0, block.seconds || 0);
    }
    if (block.mode === 'timer') return total + Math.max(0, block.seconds || 0);
    return total;
  }, 0);
  return workoutSeconds + (hasWork ? PREPARATION_BLOCK_SECONDS : 0);
}
