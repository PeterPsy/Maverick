import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('frontend performance guardrails', () => {
  const appSource = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
  const bootstrapCacheSource = readFileSync(new URL('./bootstrapCache.ts', import.meta.url), 'utf8');
  const sidebarSource = readFileSync(new URL('./widgets/fitness-coach-sidebar/main.tsx', import.meta.url), 'utf8');
  const packageJson = readFileSync(new URL('../../package.json', import.meta.url), 'utf8');

  it('uses bootstrap for initial app data without fetching runs in the first Promise.all', () => {
    expect(appSource).toContain('readCachedBootstrap({ includeRuns: false, migrationSeed, signal: controller.signal })');
    expect(appSource).not.toContain('writeBootstrapCache');
    expect(appSource).not.toContain('applyBootstrapPayload(cached)');
    expect(appSource).not.toContain('Promise.all([listWorkouts(), listExercises(libraryQuery, libraryTag), listRuns');
    expect(appSource).toContain('listRuns(selectedWorkoutId)');
  });

  it('opens the player optimistically before awaiting the atomic start response', () => {
    const startPosition = appSource.indexOf('const startPromise = startWorkout(workoutToStart.id, workoutToStart)');
    const optimisticPosition = appSource.indexOf('setPlayerSession({ workout: workoutToStart, startPromise });');
    const handledRejectionPosition = appSource.indexOf('void startPromise.catch(() => undefined);');
    const finishGatePosition = appSource.indexOf('completeWorkoutAfterConfirmedStart({');

    expect(startPosition).toBeGreaterThan(0);
    expect(handledRejectionPosition).toBeGreaterThan(startPosition);
    expect(optimisticPosition).toBeGreaterThan(startPosition);
    expect(finishGatePosition).toBeGreaterThan(optimisticPosition);
    expect(appSource).not.toContain('await saveWorkout(workoutToStart)');
  });

  it('keeps heavy tag input dependencies out of the initial bundle path', () => {
    const tagsInputSource = readFileSync(new URL('./components/ui/tags-input.tsx', import.meta.url), 'utf8');
    expect(packageJson).not.toContain('@ark-ui/react');
    expect(tagsInputSource).not.toContain('@ark-ui/react');
    expect(tagsInputSource).not.toContain('id="fitness-tags-input"');
    expect(tagsInputSource).toContain('useId');
  });

  it('requires an explicit current workspace scope for bootstrap cache reads', () => {
    expect(bootstrapCacheSource).toContain('if (requireWorkspace && !workspaceId) return null;');
    expect(bootstrapCacheSource).toContain('payload.workspace_id');
    expect(bootstrapCacheSource).not.toContain('readBootstrapCacheScopeIndex');
    expect(bootstrapCacheSource).not.toContain('bootstrap-scope');
    expect(bootstrapCacheSource).not.toContain("params.get('workspace_id') || params.get('workspace') || 'default'");
  });

  it('debounces sidebar search backend queries', () => {
    expect(sidebarSource).toContain('debouncedQuery');
    expect(sidebarSource).toContain('setTimeout(() => setDebouncedQuery(query.trim()), 180)');
    expect(sidebarSource).toContain('listWorkouts(debouncedQuery)');
  });

  it('lazy-loads media thumbnails before requesting video metadata', () => {
    expect(appSource).toContain('IntersectionObserver');
    expect(appSource).toContain("preload={isVisible ? 'metadata' : 'none'}");
    expect(appSource).toContain('src={visiblePreviewUrl ? withVideoFrameHint(visiblePreviewUrl) : undefined}');
  });

  it('reuses parent-brokered workout-setting video preview frames without a parallel local writer', () => {
    const thumbCacheSource = readFileSync(new URL('./mediaThumbPreviewCache.ts', import.meta.url), 'utf8');
    expect(appSource).toContain('readMediaThumbPreviewFrame(previewFrameKey)');
    expect(appSource).toContain('captureMediaThumbVideoFrame(event.currentTarget, previewFrameKey)');
    expect(thumbCacheSource).toContain("const THUMB_PREVIEW_STORAGE_KEY = 'fitness-coach:media-thumb-preview:v1';");
    expect(thumbCacheSource).toContain('globalThis.sessionStorage');
    expect(thumbCacheSource).toContain('legacySeeds');
    expect(thumbCacheSource).not.toContain('sessionStorage.setItem');
  });
});
