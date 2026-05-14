import { describe, expect, it } from 'vitest';
import {
  readStorageFileDragData,
  readStorageFolderDragData,
  readStorageSelectionDragData,
  storageDragPayloadFromFile,
  storageDragPayloadFromFolder,
  storageDragPayloadFromSelection,
  storageFileDropStatus,
  storageMoveDropStatus,
  writeStorageFileDragData,
  writeStorageFolderDragData,
  writeStorageSelectionDragData,
  type StorageFileDragPayload,
  type StorageFolderDragPayload,
  type StorageSelectionDragPayload,
} from './storageDragDrop';
import type { StorageFile, StorageFolder } from '../types';

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

function storageFolder(overrides: Partial<StorageFolder> = {}): StorageFolder {
  return {
    id: 'generated:reports/',
    modified_at: '2026-05-13T00:00:00Z',
    name: 'reports',
    relative_path: 'reports',
    role: 'generated',
    workspace_relative_path: 'storage/generated/reports',
    ...overrides,
  };
}

function writePayload(payload: StorageFileDragPayload) {
  const dataTransfer = new FakeDataTransfer();
  writeStorageFileDragData(dataTransfer, payload);
  return dataTransfer;
}

function writeFolderPayload(payload: StorageFolderDragPayload) {
  const dataTransfer = new FakeDataTransfer();
  writeStorageFolderDragData(dataTransfer, payload);
  return dataTransfer;
}

function writeSelectionPayload(payload: StorageSelectionDragPayload) {
  const dataTransfer = new FakeDataTransfer();
  writeStorageSelectionDragData(dataTransfer, payload);
  return dataTransfer;
}

describe('Storage drag and drop payloads', () => {
  it('serializes Storage files as logical move references', () => {
    const dataTransfer = writePayload(storageDragPayloadFromFile(storageFile(), 'storage'));

    expect(dataTransfer.effectAllowed).toBe('copyMove');
    expect(storageFileDropStatus(dataTransfer, 'generated')).toBe('ready');
    expect(storageMoveDropStatus(dataTransfer, 'generated')).toBe('ready');
    expect(readStorageFileDragData(dataTransfer, 'storage')).toEqual({
      file_id: 'file_123',
      name: 'report.md',
      owner_app_id: 'storage',
      preview_kind: 'markdown',
      relative_path: 'reports/report.md',
      role: 'generated',
      workspace_relative_path: 'storage/generated/reports/report.md',
    });
  });

  it('serializes Storage folders as logical move references', () => {
    const dataTransfer = writeFolderPayload(storageDragPayloadFromFolder(storageFolder(), 'storage'));

    expect(dataTransfer.effectAllowed).toBe('copyMove');
    expect(storageFileDropStatus(dataTransfer, 'generated')).toBe('none');
    expect(storageMoveDropStatus(dataTransfer, 'generated')).toBe('ready');
    expect(readStorageFolderDragData(dataTransfer, 'storage')).toEqual({
      folder_id: 'generated:reports/',
      name: 'reports',
      owner_app_id: 'storage',
      relative_path: 'reports',
      role: 'generated',
      workspace_relative_path: 'storage/generated/reports',
    });
  });

  it('serializes selected Storage items as one grouped move reference', () => {
    const dataTransfer = writeSelectionPayload(storageDragPayloadFromSelection({
      files: [storageFile()],
      folders: [storageFolder()],
    }, 'storage'));

    expect(dataTransfer.effectAllowed).toBe('copyMove');
    expect(storageMoveDropStatus(dataTransfer, 'generated')).toBe('ready');
    expect(readStorageSelectionDragData(dataTransfer, 'storage')).toEqual({
      files: [{
        file_id: 'file_123',
        name: 'report.md',
        owner_app_id: 'storage',
        preview_kind: 'markdown',
        relative_path: 'reports/report.md',
        role: 'generated',
        workspace_relative_path: 'storage/generated/reports/report.md',
      }],
      folders: [{
        folder_id: 'generated:reports/',
        name: 'reports',
        owner_app_id: 'storage',
        relative_path: 'reports',
        role: 'generated',
        workspace_relative_path: 'storage/generated/reports',
      }],
      owner_app_id: 'storage',
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
    expect(storageMoveDropStatus(dataTransfer, 'all')).toBe('blocked');

    const folderTransfer = writeFolderPayload(storageDragPayloadFromFolder(
      storageFolder({
        relative_path: 'Receipts',
        role: 'uploaded',
        workspace_relative_path: 'storage/uploaded/Receipts',
      }),
      'storage',
    ));
    expect(storageMoveDropStatus(folderTransfer, 'uploaded')).toBe('ready');
    expect(storageMoveDropStatus(folderTransfer, 'generated')).toBe('blocked');

    const mixedSelection = writeSelectionPayload(storageDragPayloadFromSelection({
      files: [storageFile({
        relative_path: 'report.md',
        role: 'uploaded',
        workspace_relative_path: 'storage/uploaded/report.md',
      })],
      folders: [storageFolder()],
    }, 'storage'));
    expect(storageMoveDropStatus(mixedSelection, 'uploaded')).toBe('blocked');
    expect(storageMoveDropStatus(mixedSelection, 'generated')).toBe('blocked');
  });

  it('ignores malformed payloads and payloads from another mounted app', () => {
    const malformed = new FakeDataTransfer();
    malformed.setData('application/x-maverick-storage-file', '{broken');

    expect(readStorageFileDragData(malformed, 'storage')).toBeNull();

    const otherApp = writePayload(storageDragPayloadFromFile(storageFile(), 'storage-fork'));
    expect(readStorageFileDragData(otherApp, 'storage')).toBeNull();

    const malformedFolder = new FakeDataTransfer();
    malformedFolder.setData('application/x-maverick-storage-folder', '{broken');
    expect(readStorageFolderDragData(malformedFolder, 'storage')).toBeNull();

    const otherAppFolder = writeFolderPayload(storageDragPayloadFromFolder(storageFolder(), 'storage-fork'));
    expect(readStorageFolderDragData(otherAppFolder, 'storage')).toBeNull();

    const malformedSelection = new FakeDataTransfer();
    malformedSelection.setData('application/x-maverick-storage-selection', '{broken');
    expect(readStorageSelectionDragData(malformedSelection, 'storage')).toBeNull();

    const nonArraySelection = new FakeDataTransfer();
    nonArraySelection.setData('application/x-maverick-storage-selection', JSON.stringify({
      files: {},
      folders: [],
      owner_app_id: 'storage',
    }));
    expect(readStorageSelectionDragData(nonArraySelection, 'storage')).toBeNull();

    const otherAppSelection = writeSelectionPayload(storageDragPayloadFromSelection({
      files: [storageFile()],
      folders: [],
    }, 'storage-fork'));
    expect(readStorageSelectionDragData(otherAppSelection, 'storage')).toBeNull();
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

    const folderDataTransfer = writeFolderPayload({
      folder_id: 'generated:reports/',
      name: 'reports',
      owner_app_id: 'storage',
      relative_path: '../reports',
      role: 'generated',
      workspace_relative_path: 'storage/generated/../reports',
    });

    expect(readStorageFolderDragData(folderDataTransfer, 'storage')).toBeNull();

    const selectionDataTransfer = writeSelectionPayload({
      files: [{
        file_id: 'file_123',
        name: 'report.md',
        owner_app_id: 'storage',
        relative_path: '../report.md',
        role: 'generated',
        workspace_relative_path: 'storage/generated/../report.md',
      }],
      folders: [],
      owner_app_id: 'storage',
    });

    expect(readStorageSelectionDragData(selectionDataTransfer, 'storage')).toBeNull();
  });
});
