import {
  readMaverickAppFrameContext,
  readThroughParentDataCache,
  readCacheModelJson,
  type ParentDataCacheReadResult
} from '@maverick/pwa-cache';
import { callBackend, currentStorageAppId, mountedAppIdFromPath } from './api';
import { sanitizeBootstrapReadModel } from './bootstrapCache';
import type { AppBootstrapPayload } from './types';

export type CachedBootstrapOptions = {
  includeRuns?: boolean;
  selectedWorkoutId?: string | null;
  signal?: AbortSignal;
};

export async function readCachedBootstrap(
  options: CachedBootstrapOptions = {},
): Promise<ParentDataCacheReadResult<AppBootstrapPayload>> {
  const appId = mountedAppIdFromPath(
    typeof window === 'undefined' ? '' : window.location.pathname,
    'fitness-coach'
  );
  const frameContext = readMaverickAppFrameContext();
  const frameContextMatchesMount = !frameContext || frameContext.appId === appId;
  const storageAppId = currentStorageAppId();
  const includeRuns = options.includeRuns === true;
  const selectedWorkoutId = String(options.selectedWorkoutId || 'active');
  const sanitize = (value: unknown) => {
    const payload = sanitizeBootstrapReadModel(value);
    if (!payload
        || !frameContextMatchesMount
        || payload.app_id !== appId
        || (frameContext && payload.workspace_id !== frameContext.workspaceId)) return null;
    return payload;
  };
  return readThroughParentDataCache<AppBootstrapPayload>({
    appId,
    entityId: `bootstrap:${storageAppId}:${includeRuns ? 'runs' : 'no-runs'}:${selectedWorkoutId}`,
    resource: 'sanitized-bootstrap-and-thumbnails',
    schemaRevision: 'fitness-coach.sanitized-bootstrap-and-thumbnails.v1'
  }, async ({ knownRevision, signal }) => {
    const parameters = {
      include_runs: includeRuns, selected_workout_id: options.selectedWorkoutId || '',
      storage_app_id: storageAppId, known_revision: knownRevision
    };
    const payload = appId === 'fitness-coach'
      ? await readCacheModelJson<AppBootstrapPayload>({
          appId, resource: 'sanitized-bootstrap-and-thumbnails', parameters
        }, signal)
      : await callBackend<AppBootstrapPayload>({ action: 'app.bootstrap', ...parameters }, { signal });
    if (payload.not_modified) {
      if (!knownRevision || payload.state_version !== knownRevision) {
        throw new TypeError('Fitness Coach returned not_modified without the requested revision.');
      }
      return { kind: 'not_modified', revision: knownRevision } as const;
    }
    const sanitized = sanitize(payload);
    if (!sanitized) throw new TypeError('Fitness Coach returned an invalid bootstrap read model.');
    return { kind: 'value', payload: sanitized, revision: sanitized.state_version } as const;
  }, {
    sanitize,
    signal: options.signal
  });
}
