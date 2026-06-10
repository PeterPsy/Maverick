import { afterEach, describe, expect, it, vi } from 'vitest';
import { readBootstrapCache, writeBootstrapCache } from './bootstrapCache';
import type { AppBootstrapPayload } from './types';

function bootstrapPayload(overrides: Partial<AppBootstrapPayload> = {}): AppBootstrapPayload {
  return {
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

describe('bootstrap cache', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not read a cache scope when neither URL nor validated index provides a workspace', () => {
    stubWindow('');

    expect(readBootstrapCache()).toBeNull();
  });

  it('uses the last backend-validated scope for reload prepaint without workspace query params', () => {
    const { values } = stubWindow('');
    writeBootstrapCache({
      ...bootstrapPayload(),
      stream_url: 'must-not-persist'
    } as unknown as AppBootstrapPayload);

    expect(readBootstrapCache()).toEqual(bootstrapPayload());
    expect(Array.from(values.values()).join('\n')).not.toContain('must-not-persist');
  });

  it('prefers an explicit URL workspace over the stored scope index', () => {
    const { sessionStorage } = stubWindow('');
    writeBootstrapCache(bootstrapPayload());
    vi.stubGlobal('window', { location: { search: '?workspace_id=other' }, sessionStorage });

    expect(readBootstrapCache()).toBeNull();
  });
});
