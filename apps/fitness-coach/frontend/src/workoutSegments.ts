import type { RuntimeSegment, WorkBlock, Workout } from './types';

export const REPS_PROGRESS_SECONDS = 60;

export function runtimeSegmentsForWorkout(workout: Workout): RuntimeSegment[] {
  const segments: RuntimeSegment[] = [];
  workout.blocks.forEach((block, index) => {
    if (block.type === 'work') {
      if (!block.media) return;
      segments.push({
        type: 'work',
        blockId: block.id,
        mode: block.mode,
        media: block.media,
        title: block.title,
        short_description: block.short_description || block.long_description,
        long_description: block.long_description || block.short_description,
        seconds: block.mode === 'timer' ? block.seconds || undefined : undefined,
        repsLabel: block.mode === 'reps' ? repsLabel(block) : undefined
      });
      return;
    }
    const nextWork = workout.blocks.slice(index + 1).find((candidate): candidate is WorkBlock => candidate.type === 'work');
    if (!nextWork && block.skip_if_last) return;
    segments.push({
      type: 'rest',
      blockId: block.id,
      title: block.title,
      short_description: block.short_description,
      long_description: block.long_description,
      seconds: block.seconds,
      nextWorkSegmentId: nextWork?.id || null,
      showNextExercise: block.show_next_exercise
    });
  });
  return segments;
}

export function repsLabel(block: WorkBlock): string {
  const explicitLabel = block.reps_label?.trim();
  if (explicitLabel) return /^\d+(?:[.,]\d+)?$/.test(explicitLabel) ? `${explicitLabel} reps` : explicitLabel;
  return `${block.reps || 0} reps`;
}

export function segmentProgressSeconds(segment: RuntimeSegment | null | undefined): number {
  if (!segment) return 0;
  if (segment.type === 'work' && segment.mode === 'reps') return REPS_PROGRESS_SECONDS;
  return Math.max(0, segment.seconds || 0);
}

export function segmentProgressRepeats(segment: RuntimeSegment | null | undefined): boolean {
  return segment?.type === 'work' && segment.mode === 'reps';
}
