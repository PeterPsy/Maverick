import { afterEach, describe, expect, it, vi } from 'vitest';
import { readBootstrapCache, removeBootstrapCache, sanitizeBootstrapReadModel } from './bootstrapCache';
import type { AppBootstrapPayload } from './types';

function bootstrapPayload(overrides: Partial<AppBootstrapPayload> = {}): AppBootstrapPayload {
  return {
    schema: 'fitness-coach.bootstrap.v1',
    workspace_id: 'default',
    app_id: 'fitness-coach',
    state_version: 'v1',
    workouts: [],
    workout_summaries: [],
    selected_workout: null,
    exercises: [],
    tags: [],
    runs: [],
    view_state: { selected_workout_id: null, setup_tab: 'workout-settings', sidebar_query: '' },
    ...overrides
  };
}

function stubWindow(context?: { app_id: string; workspace_id: string }) {
  const values = new Map<string, string>();
  const sessionStorage = {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
    removeItem: vi.fn((key: string) => { values.delete(key); }),
    clear: vi.fn(() => { values.clear(); }),
    key: vi.fn((index: number) => Array.from(values.keys())[index] ?? null),
    get length() { return values.size; }
  } as Storage;
  vi.stubGlobal('window', {
    ...(context ? { __MAVERICK_APP_FRAME_CONTEXT__: Object.freeze(context) } : {}),
    location: { pathname: '/apps/fitness-coach/', search: '' },
    sessionStorage
  });
  return { values, sessionStorage };
}

function seedLegacyBootstrap(values: Map<string, string>, value: unknown, workspaceId = 'default') {
  values.set(`fitness-coach:bootstrap:${workspaceId}:fitness-coach:storage`, JSON.stringify({
    version: 1,
    cached_at: '2026-09-03T00:00:00.000Z',
    payload: value
  }));
}

describe('bootstrap cache', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not read a cache scope without host-attested frame context', () => {
    stubWindow();

    expect(readBootstrapCache()).toBeNull();
  });

  it('does not prepaint cached workspace data after a host-attested workspace switch', () => {
    const { values } = stubWindow({ app_id: 'fitness-coach', workspace_id: 'other' });
    seedLegacyBootstrap(values, {
      ...bootstrapPayload(),
      stream_url: 'must-not-persist'
    }, 'other');

    expect(readBootstrapCache()).toBeNull();
  });

  it('rejects unknown nested fields as well as credentials and signed URLs', () => {
    const sanitized = sanitizeBootstrapReadModel({
      ...bootstrapPayload(),
      nested: {
        accessToken: 'secret-token',
        signed_url: 'https://files.test/item?X-Amz-Signature=secret',
        safe_label: 'Workout A'
      }
    });

    const serialized = JSON.stringify(sanitized);
    expect(serialized).not.toContain('secret-token');
    expect(serialized).not.toContain('X-Amz-Signature');
    expect(serialized).not.toContain('Workout A');
  });

  it('does not migrate legacy data without user scope even when workspace and app match', () => {
    const { values } = stubWindow({ app_id: 'fitness-coach', workspace_id: 'default' });
    seedLegacyBootstrap(values, bootstrapPayload());

    expect(readBootstrapCache()).toBeNull();
  });

  it('does not read cached data when the host workspace differs from the payload scope', () => {
    const { values } = stubWindow({ app_id: 'fitness-coach', workspace_id: 'other' });
    seedLegacyBootstrap(values, bootstrapPayload(), 'other');

    expect(readBootstrapCache()).toBeNull();
  });

  it('removes only the legacy key matching the current host-attested scope', () => {
    const { values, sessionStorage } = stubWindow({ app_id: 'fitness-coach', workspace_id: 'default' });
    seedLegacyBootstrap(values, bootstrapPayload());

    removeBootstrapCache(bootstrapPayload({ workspace_id: 'other' }));
    expect(sessionStorage.removeItem).not.toHaveBeenCalled();

    removeBootstrapCache(bootstrapPayload());
    expect(sessionStorage.removeItem).toHaveBeenCalledWith(
      'fitness-coach:bootstrap:default:fitness-coach:storage'
    );
  });

  it('rejects a cache-poisoned bootstrap whose app records do not match the schema', () => {
    expect(sanitizeBootstrapReadModel({
      ...bootstrapPayload(),
      workouts: ['not-a-workout']
    })).toBeNull();
  });

  it('rejects a broker payload with the wrong schema identifier', () => {
    expect(sanitizeBootstrapReadModel({
      ...bootstrapPayload(),
      schema: 'fitness-coach.bootstrap.v2'
    } as unknown as AppBootstrapPayload)).toBeNull();
  });
});
