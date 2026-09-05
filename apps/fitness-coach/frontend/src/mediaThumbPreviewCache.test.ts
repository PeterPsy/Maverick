import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  PWA_DATA_CACHE_BROKER_ACCEPTED,
  PWA_DATA_CACHE_BROKER_NETWORK_REQUEST,
  PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
  PWA_DATA_CACHE_BROKER_RESULT
} from '@maverick/pwa-cache';
import {
  clearMediaThumbPreviewFrameCache,
  mediaThumbPreviewFrameKey,
  readMediaThumbPreviewFrame,
  THUMB_PREVIEW_CACHE_CHANGED_EVENT,
  writeMediaThumbPreviewFrame
} from './mediaThumbPreviewCache';
import type { ExerciseMediaRef } from './types';

function storageMock(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    values,
    storage: {
      getItem: vi.fn((key: string) => values.get(key) || null),
      setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
      removeItem: vi.fn((key: string) => { values.delete(key); }),
      clear: vi.fn(() => values.clear()),
      key: vi.fn((index: number) => Array.from(values.keys())[index] || null),
      get length() {
        return values.size;
      }
    } as Storage
  };
}

function stubFrame(parent: Pick<Window, 'postMessage'>) {
  const frameWindow = new EventTarget() as EventTarget & Window & { __MAVERICK_PLATFORM_ORIGIN__: string };
  Object.assign(frameWindow, {
    __MAVERICK_PLATFORM_ORIGIN__: 'https://maverick.test',
    location: {
      origin: 'https://fitness-coach.sidecars.maverick.test',
      pathname: '/apps/fitness-coach/'
    },
    parent
  });
  vi.stubGlobal('window', frameWindow);
  return frameWindow;
}

function postAccepted(message: Record<string, unknown>, port: MessagePort) {
  port.postMessage({
    app_id: message.app_id,
    request_id: message.request_id,
    type: PWA_DATA_CACHE_BROKER_ACCEPTED
  });
}

const videoMedia: Extract<ExerciseMediaRef, { kind: 'local_file' }> = {
  kind: 'local_file',
  provider: 'local',
  file_id: 'file_preview',
  workspace_relative_path: 'storage/uploaded/preview.mp4',
  display_path: 'storage/uploaded/preview.mp4',
  name: 'preview.mp4',
  content_type: 'video/mp4',
  preview_kind: 'video',
  etag_or_version: 'v1'
};

const storageKey = 'fitness-coach:media-thumb-preview:v1';
const frame = 'data:image/jpeg;base64,ZmFrZS1mcmFtZQ==';

describe('media thumb preview cache', () => {
  afterEach(() => {
    clearMediaThumbPreviewFrameCache();
    vi.unstubAllGlobals();
  });

  it('keys cached frames by media identity and source version', () => {
    const first = mediaThumbPreviewFrameKey(videoMedia, 'storage');
    const changed = mediaThumbPreviewFrameKey({ ...videoMedia, etag_or_version: 'v2' }, 'storage');

    expect(first).toContain('thumb-frame:storage:local_file:file_preview:v1');
    expect(changed).toContain('thumb-frame:storage:local_file:file_preview:v2');
    expect(changed).not.toBe(first);
  });

  it('does not migrate a thumbnail whose media source has no stable version', async () => {
    const key = mediaThumbPreviewFrameKey({ ...videoMedia, etag_or_version: '' }, 'storage');
    const { storage, values } = storageMock({
      [storageKey]: JSON.stringify({ entries: [{ key, dataUrl: frame, updatedAt: 10 }] })
    });
    vi.stubGlobal('sessionStorage', storage);
    const postMessage = vi.fn();
    stubFrame({ postMessage } as Pick<Window, 'postMessage'>);

    expect(readMediaThumbPreviewFrame(key)).toBe('');
    await Promise.resolve();

    expect(postMessage).not.toHaveBeenCalled();
    expect(values.has(storageKey)).toBe(false);
  });

  it('never prepaints a legacy session value when the parent cache is unavailable', async () => {
    const key = mediaThumbPreviewFrameKey(videoMedia, 'storage');
    const { storage, values } = storageMock({
      [storageKey]: JSON.stringify({ entries: [{ key, dataUrl: frame, updatedAt: 10 }] })
    });
    vi.stubGlobal('sessionStorage', storage);
    stubFrame({
      postMessage(message: unknown, _origin: string, transfer?: Transferable[]) {
        const payload = message as Record<string, unknown>;
        const port = transfer?.[0] as MessagePort;
        postAccepted(payload, port);
        port.postMessage({
          app_id: payload.app_id,
          phase: 'initial',
          request_id: payload.request_id,
          status: 'unavailable',
          type: PWA_DATA_CACHE_BROKER_RESULT
        });
      }
    } as Pick<Window, 'postMessage'>);

    expect(readMediaThumbPreviewFrame(key)).toBe('');
    await vi.waitFor(() => expect(values.has(storageKey)).toBe(false));
    expect(readMediaThumbPreviewFrame(key)).toBe('');
  });

  it('persists a newly captured frame but discards its unscoped legacy source', async () => {
    const key = mediaThumbPreviewFrameKey(videoMedia, 'storage');
    const entry = { key, dataUrl: frame, updatedAt: 10 };
    const { storage, values } = storageMock({
      [storageKey]: JSON.stringify({ entries: [entry] })
    });
    vi.stubGlobal('sessionStorage', storage);
    const frameWindow = stubFrame({
      postMessage(message: unknown, _origin: string, transfer?: Transferable[]) {
        const payload = message as Record<string, unknown>;
        const port = transfer?.[0] as MessagePort;
        expect(payload.migration_seed).toMatchObject({ payload: { key, dataUrl: frame } });
        postAccepted(payload, port);
        port.postMessage({
          app_id: payload.app_id,
          freshness: 'fresh',
          migration_committed: true,
          payload: entry,
          phase: 'initial',
          request_id: payload.request_id,
          revision: (payload.migration_seed as { revision: string }).revision,
          source: 'cache',
          status: 'ok',
          type: PWA_DATA_CACHE_BROKER_RESULT
        });
      }
    } as Pick<Window, 'postMessage'>);
    const changed = new Promise<void>((resolve) => {
      frameWindow.addEventListener(THUMB_PREVIEW_CACHE_CHANGED_EVENT, () => resolve(), { once: true });
    });

    writeMediaThumbPreviewFrame(key, frame);
    await changed;
    expect(readMediaThumbPreviewFrame(key)).toBe(frame);
    expect(values.has(storageKey)).toBe(false);
  });

  it('treats a parent-cached thumbnail as current when its media identity is unchanged', async () => {
    const key = mediaThumbPreviewFrameKey(videoMedia, 'storage');
    const entry = { key, dataUrl: frame, updatedAt: 10 };
    const revision = 'a'.repeat(64);
    const { storage } = storageMock();
    vi.stubGlobal('sessionStorage', storage);
    let resolveNetwork!: () => void;
    const networkCompleted = new Promise<void>((resolve) => { resolveNetwork = resolve; });
    const frameWindow = stubFrame({
      postMessage(message: unknown, _origin: string, transfer?: Transferable[]) {
        const payload = message as Record<string, unknown>;
        const port = transfer?.[0] as MessagePort;
        expect(payload).not.toHaveProperty('migration_seed');
        port.addEventListener('message', (event) => {
          const response = event.data as Record<string, unknown>;
          if (response.type !== PWA_DATA_CACHE_BROKER_NETWORK_RESULT) return;
          expect(response).toMatchObject({ kind: 'not_modified', revision, status: 'ok' });
          port.postMessage({
            app_id: payload.app_id,
            changed: false,
            payload: entry,
            phase: 'revalidation',
            request_id: payload.request_id,
            revision,
            status: 'ok',
            type: PWA_DATA_CACHE_BROKER_RESULT
          });
          resolveNetwork();
        });
        port.start();
        postAccepted(payload, port);
        port.postMessage({
          app_id: payload.app_id,
          freshness: 'fresh',
          has_revalidation: true,
          payload: entry,
          phase: 'initial',
          request_id: payload.request_id,
          revision,
          source: 'cache',
          status: 'ok',
          type: PWA_DATA_CACHE_BROKER_RESULT
        });
        port.postMessage({
          app_id: payload.app_id,
          known_revision: revision,
          network_request_id: 'network-one',
          request_id: payload.request_id,
          type: PWA_DATA_CACHE_BROKER_NETWORK_REQUEST
        });
      }
    } as Pick<Window, 'postMessage'>);
    const changed = new Promise<void>((resolve) => {
      frameWindow.addEventListener(THUMB_PREVIEW_CACHE_CHANGED_EVENT, () => resolve(), { once: true });
    });

    expect(readMediaThumbPreviewFrame(key)).toBe('');
    await changed;
    await networkCompleted;
    expect(readMediaThumbPreviewFrame(key)).toBe(frame);
  });

  it('keeps a newly captured frame in page memory without writing a second local cache', async () => {
    const key = mediaThumbPreviewFrameKey(videoMedia, 'storage');
    const { storage, values } = storageMock();
    vi.stubGlobal('sessionStorage', storage);
    stubFrame({
      postMessage(message: unknown, _origin: string, transfer?: Transferable[]) {
        const payload = message as Record<string, unknown>;
        const port = transfer?.[0] as MessagePort;
        postAccepted(payload, port);
        port.postMessage({
          app_id: payload.app_id,
          phase: 'initial',
          request_id: payload.request_id,
          status: 'unavailable',
          type: PWA_DATA_CACHE_BROKER_RESULT
        });
      }
    } as Pick<Window, 'postMessage'>);

    writeMediaThumbPreviewFrame(key, frame);

    expect(readMediaThumbPreviewFrame(key)).toBe(frame);
    await Promise.resolve();
    expect(values.has(storageKey)).toBe(false);
  });
});
