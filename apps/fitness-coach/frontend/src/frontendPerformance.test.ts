import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('frontend performance guardrails', () => {
  const appSource = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
  const sidebarSource = readFileSync(new URL('./widgets/fitness-coach-sidebar/main.tsx', import.meta.url), 'utf8');
  const packageJson = readFileSync(new URL('../../package.json', import.meta.url), 'utf8');

  it('uses bootstrap for initial app data without fetching runs in the first Promise.all', () => {
    expect(appSource).toContain("bootstrapApp({ includeRuns: false })");
    expect(appSource).not.toContain('Promise.all([listWorkouts(), listExercises(libraryQuery, libraryTag), listRuns');
    expect(appSource).toContain('listRuns(selectedWorkoutId)');
  });

  it('opens the player optimistically before awaiting the atomic start response', () => {
    const optimisticPosition = appSource.indexOf('setPlayerWorkout(workoutToStart);');
    const startPosition = appSource.indexOf('await startWorkout(workoutToStart.id, workoutToStart);');

    expect(optimisticPosition).toBeGreaterThan(0);
    expect(startPosition).toBeGreaterThan(optimisticPosition);
    expect(appSource).not.toContain('await saveWorkout(workoutToStart)');
  });

  it('keeps heavy tag input dependencies out of the initial bundle path', () => {
    expect(packageJson).not.toContain('@ark-ui/react');
    expect(readFileSync(new URL('./components/ui/tags-input.tsx', import.meta.url), 'utf8')).not.toContain('@ark-ui/react');
  });

  it('debounces sidebar search backend queries', () => {
    expect(sidebarSource).toContain('debouncedQuery');
    expect(sidebarSource).toContain('setTimeout(() => setDebouncedQuery(query.trim()), 180)');
    expect(sidebarSource).toContain('listWorkouts(debouncedQuery)');
  });

  it('lazy-loads media thumbnails instead of eager video metadata preload', () => {
    expect(appSource).toContain('IntersectionObserver');
    expect(appSource).toContain('preload="none"');
    expect(appSource).not.toContain('preload="metadata"');
  });
});
