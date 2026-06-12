import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearMediaThumbPreviewFrameCache, mediaThumbPreviewFrameKey, readMediaThumbPreviewFrame, writeMediaThumbPreviewFrame } from './mediaThumbPreviewCache';
import type { ExerciseMediaRef } from './types';

function storageMock() {
  const values = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => values.get(key) || null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
    removeItem: vi.fn((key: string) => { values.delete(key); }),
    clear: vi.fn(() => values.clear()),
    key: vi.fn((index: number) => Array.from(values.keys())[index] || null),
    get length() {
      return values.size;
    }
  } as Storage;
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

  it('persists thumbnail frames across app remounts in the same browser session', () => {
    vi.stubGlobal('sessionStorage', storageMock());
    const key = mediaThumbPreviewFrameKey(videoMedia, 'storage');
    const frame = 'data:image/jpeg;base64,ZmFrZS1mcmFtZQ==';

    writeMediaThumbPreviewFrame(key, frame);
    clearMediaThumbPreviewFrameCache({ storage: false });

    expect(readMediaThumbPreviewFrame(key)).toBe(frame);
  });
});
