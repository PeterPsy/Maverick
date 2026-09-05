import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  PWA_DATA_CACHE_BROKER_ACCEPTED,
  PWA_DATA_CACHE_BROKER_NETWORK_REQUEST,
  PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
  PWA_DATA_CACHE_BROKER_RESULT
} from '@maverick/pwa-cache';
import { readCachedBootstrap } from './bootstrapReadModelCache';
import type { AppBootstrapPayload } from './types';

function payload(stateVersion: string, workspaceId = 'default'): AppBootstrapPayload {
  return {
    schema: 'fitness-coach.bootstrap.v1',
    workspace_id: workspaceId,
    app_id: 'fitness-coach',
    state_version: stateVersion,
    workouts: [],
    workout_summaries: [],
    selected_workout: null,
    exercises: [],
    tags: [],
    runs: [],
    view_state: {
      selected_workout_id: null,
      setup_tab: 'workout-settings',
      sidebar_query: ''
    }
  };
}

function stubFrame(parent: Pick<Window, 'postMessage'>) {
  const frameWindow = new EventTarget() as EventTarget & Window & {
    __MAVERICK_APP_FRAME_CONTEXT__: Readonly<{ app_id: string; workspace_id: string }>;
    __MAVERICK_PLATFORM_ORIGIN__: string;
  };
  Object.assign(frameWindow, {
    __MAVERICK_APP_FRAME_CONTEXT__: Object.freeze({
      app_id: 'fitness-coach',
      workspace_id: 'default'
    }),
    __MAVERICK_PLATFORM_ORIGIN__: 'https://maverick.test',
    location: {
      origin: 'https://fitness-coach.sidecars.maverick.test',
      pathname: '/apps/fitness-coach/',
      search: ''
    },
    parent
  });
  vi.stubGlobal('window', frameWindow);
}

function accept(message: Record<string, unknown>, port: MessagePort) {
  port.postMessage({
    app_id: message.app_id,
    request_id: message.request_id,
    type: PWA_DATA_CACHE_BROKER_ACCEPTED
  });
}

describe('Fitness Coach parent-cached bootstrap adapter', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses a normal server read without any unscoped migration seed when the broker is disabled', async () => {
    const server = payload('server');
    stubFrame({
      postMessage(message: unknown, _origin: string, transfer?: Transferable[]) {
        const request = message as Record<string, unknown>;
        const port = transfer?.[0] as MessagePort;
        expect(request).not.toHaveProperty('migration_seed');
        accept(request, port);
        port.postMessage({
          app_id: request.app_id,
          phase: 'initial',
          request_id: request.request_id,
          status: 'unavailable',
          type: PWA_DATA_CACHE_BROKER_RESULT
        });
      }
    } as Pick<Window, 'postMessage'>);
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).not.toHaveProperty('known_revision');
      return new Response(JSON.stringify(server), {
        headers: { 'Content-Type': 'application/json' },
        status: 200
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await readCachedBootstrap({ includeRuns: false });

    expect(result).toMatchObject({ brokered: false, payload: server, source: 'network' });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('rejects a bootstrap read model outside the mounted workspace scope', async () => {
    stubFrame({
      postMessage(message: unknown, _origin: string, transfer?: Transferable[]) {
        const request = message as Record<string, unknown>;
        const port = transfer?.[0] as MessagePort;
        accept(request, port);
        port.postMessage({
          app_id: request.app_id,
          phase: 'initial',
          request_id: request.request_id,
          status: 'unavailable',
          type: PWA_DATA_CACHE_BROKER_RESULT
        });
      }
    } as Pick<Window, 'postMessage'>);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payload('revision-one', 'other')), {
      headers: { 'Content-Type': 'application/json' },
      status: 200
    })));

    await expect(readCachedBootstrap({ includeRuns: false })).rejects.toBeInstanceOf(TypeError);
  });

  it('revalidates a warm bootstrap with its opaque server revision', async () => {
    const cached = payload('revision-one');
    stubFrame({
      postMessage(message: unknown, _origin: string, transfer?: Transferable[]) {
        const request = message as Record<string, unknown>;
        const port = transfer?.[0] as MessagePort;
        port.addEventListener('message', (event) => {
          const response = event.data as Record<string, unknown>;
          if (response.type !== PWA_DATA_CACHE_BROKER_NETWORK_RESULT) return;
          expect(response).toMatchObject({ kind: 'not_modified', revision: 'revision-one', status: 'ok' });
          port.postMessage({
            app_id: request.app_id,
            changed: false,
            payload: cached,
            phase: 'revalidation',
            request_id: request.request_id,
            revision: 'revision-one',
            status: 'ok',
            type: PWA_DATA_CACHE_BROKER_RESULT
          });
        });
        port.start();
        accept(request, port);
        port.postMessage({
          app_id: request.app_id,
          freshness: 'fresh',
          has_revalidation: true,
          payload: cached,
          phase: 'initial',
          request_id: request.request_id,
          revision: 'revision-one',
          source: 'cache',
          status: 'ok',
          type: PWA_DATA_CACHE_BROKER_RESULT
        });
        port.postMessage({
          app_id: request.app_id,
          known_revision: 'revision-one',
          network_request_id: 'network-one',
          request_id: request.request_id,
          type: PWA_DATA_CACHE_BROKER_NETWORK_REQUEST
        });
      }
    } as Pick<Window, 'postMessage'>);
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toMatchObject({ known_revision: 'revision-one' });
      return new Response(JSON.stringify({
        ok: true,
        schema: 'fitness-coach.bootstrap.v1',
        state_version: 'revision-one',
        not_modified: true
      }), {
        headers: { 'Content-Type': 'application/json' },
        status: 200
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await readCachedBootstrap({ includeRuns: false });

    expect(result).toMatchObject({ brokered: true, payload: cached, source: 'cache' });
    await expect(result.revalidation).resolves.toMatchObject({ changed: false, payload: cached });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
