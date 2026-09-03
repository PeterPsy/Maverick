import { afterEach, describe, expect, it, vi } from 'vitest';
import { readBootstrapCache, sanitizeBootstrapReadModel } from './bootstrapCache';
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

function stubWindow(search = '') {
  const values = new Map<string, string>();
  const sessionStorage = {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
    removeItem: vi.fn((key: string) => { values.delete(key); }),
    clear: vi.fn(() => { values.clear(); }),
    key: vi.fn((index: number) => Array.from(values.keys())[index] ?? null),
    get length() { return values.size; }
  } as Storage;
  vi.stubGlobal('window', { location: { search }, sessionStorage });
  return { values, sessionStorage };
}

function seedLegacyBootstrap(values: Map<string, string>, value: unknown) {
  values.set('fitness-coach:bootstrap:default:fitness-coach:storage', JSON.stringify({
    version: 1,
    cached_at: '2026-09-03T00:00:00.000Z',
    payload: value
  }));
}

describe('bootstrap cache', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not read a cache scope when the current URL does not provide a workspace', () => {
    stubWindow('');

    expect(readBootstrapCache()).toBeNull();
  });

  it('does not prepaint cached workspace data after a workspace switch leaves the iframe URL unscoped', () => {
    const { values } = stubWindow('');
    seedLegacyBootstrap(values, {
      ...bootstrapPayload(),
      stream_url: 'must-not-persist'
    });

    expect(readBootstrapCache()).toBeNull();
  });

  it('removes normalized credentials and signed URLs from a legacy migration seed', () => {
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
    expect(serialized).toContain('Workout A');
  });

  it('reads cached data only when the URL workspace matches the stored payload scope', () => {
    const { sessionStorage, values } = stubWindow('');
    seedLegacyBootstrap(values, bootstrapPayload());
    vi.stubGlobal('window', { location: { search: '?workspace_id=default' }, sessionStorage });

    expect(readBootstrapCache()).toEqual(bootstrapPayload());
  });

  it('does not read cached data when the URL workspace differs from the stored payload scope', () => {
    const { sessionStorage, values } = stubWindow('');
    seedLegacyBootstrap(values, bootstrapPayload());
    vi.stubGlobal('window', { location: { search: '?workspace_id=other' }, sessionStorage });

    expect(readBootstrapCache()).toBeNull();
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
