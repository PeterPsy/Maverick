import type { RuntimeSegment, WorkBlock, Workout } from './types';

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
        short_description: block.short_description,
        long_description: block.long_description,
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
  if (block.reps_label?.trim()) return block.reps_label.trim();
  return `${block.reps || 0} reps`;
}
