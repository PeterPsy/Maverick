import { describe, expect, it } from 'vitest';
import {
  readStorageFileDragData,
  storageDragPayloadFromFile,
  storageFileDropStatus,
  writeStorageFileDragData,
  type StorageFileDragPayload,
} from './storageDragDrop';
import type { StorageFile } from '../types';

class FakeDataTransfer {
  dropEffect: DataTransfer['dropEffect'] = 'none';
  effectAllowed: DataTransfer['effectAllowed'] = 'uninitialized';
  types: string[] = [];
  private readonly data = new Map<string, string>();

  getData(type: string) {
    return this.data.get(type.toLowerCase()) || '';
  }

  setData(type: string, value: string) {
    const normalizedType = type.toLowerCase();
    this.data.set(normalizedType, value);
    if (!this.types.includes(normalizedType)) {
      this.types.push(normalizedType);
    }
  }
}

function storageFile(overrides: Partial<StorageFile> = {}): StorageFile {
  return {
    content_type: 'text/markdown',
    extension: '.md',
    file_id: 'file_123',
    id: 'file_123',
    modified_at: '2026-05-13T00:00:00Z',
    name: 'report.md',
    path_id: 'generated:reports/report.md',
    preview_kind: 'markdown',
    relative_path: 'reports/report.md',
    role: 'generated',
    sha256: 'abc',
    size_bytes: 8,
    workspace_relative_path: 'storage/generated/reports/report.md',
    ...overrides,
  };
}

function writePayload(payload: StorageFileDragPayload) {
  const dataTransfer = new FakeDataTransfer();
  writeStorageFileDragData(dataTransfer, payload);
  return dataTransfer;
}

describe('Storage drag and drop payloads', () => {
  it('serializes Storage files as logical move references', () => {
    const dataTransfer = writePayload(storageDragPayloadFromFile(storageFile(), 'storage'));

    expect(dataTransfer.effectAllowed).toBe('move');
    expect(storageFileDropStatus(dataTransfer, 'generated')).toBe('ready');
    expect(readStorageFileDragData(dataTransfer, 'storage')).toEqual({
      file_id: 'file_123',
      name: 'report.md',
      owner_app_id: 'storage',
      relative_path: 'reports/report.md',
      role: 'generated',
      workspace_relative_path: 'storage/generated/reports/report.md',
    });
  });

  it('blocks role-incompatible targets and the aggregate Storage root', () => {
    const dataTransfer = writePayload(storageDragPayloadFromFile(
      storageFile({
        relative_path: 'report.md',
        role: 'uploaded',
        workspace_relative_path: 'storage/uploaded/report.md',
      }),
      'storage',
    ));

    expect(storageFileDropStatus(dataTransfer, 'uploaded')).toBe('ready');
    expect(storageFileDropStatus(dataTransfer, 'generated')).toBe('blocked');
    expect(storageFileDropStatus(dataTransfer, 'all')).toBe('blocked');
  });

  it('ignores malformed payloads and payloads from another mounted app', () => {
    const malformed = new FakeDataTransfer();
    malformed.setData('application/x-maverick-storage-file', '{broken');

    expect(readStorageFileDragData(malformed, 'storage')).toBeNull();

    const otherApp = writePayload(storageDragPayloadFromFile(storageFile(), 'storage-fork'));
    expect(readStorageFileDragData(otherApp, 'storage')).toBeNull();
  });

  it('rejects path escape payloads before calling the backend', () => {
    const dataTransfer = writePayload({
      file_id: 'file_123',
      name: 'report.md',
      owner_app_id: 'storage',
      relative_path: '../report.md',
      role: 'generated',
      workspace_relative_path: 'storage/generated/../report.md',
    });

    expect(readStorageFileDragData(dataTransfer, 'storage')).toBeNull();
  });
});
