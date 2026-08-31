import {
  requestParentFileCacheOpen,
  type ParentFileCacheClientOptions,
  type ParentFileCacheOpenRequest,
  type ParentFileCacheOpenResult,
} from '@maverick/pwa-cache';
import type { StorageFile } from './types';

const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const SHA256_VERSION_PATTERN = /^sha256:[0-9a-f]{64}$/u;
export const MAX_DEVICE_FILE_CACHE_ENTRY_BYTES = 64 * 1024 * 1024;

type ParentRequest = (
  request: ParentFileCacheOpenRequest,
  options?: ParentFileCacheClientOptions,
) => Promise<ParentFileCacheOpenResult | null>;

export type StorageFileCacheClientOptions = {
  maxBytes?: number;
  request?: ParentRequest;
  signal?: AbortSignal;
};

export function stableStorageFileSourceVersion(file: StorageFile): string {
  if (file.provider === 'google_drive') {
    return String(file.source_version || file.etag_or_version || '').trim();
  }
  const projected = String(file.source_version || '').trim().toLowerCase();
  if (SHA256_VERSION_PATTERN.test(projected)) return projected;
  const digest = String(file.sha256 || '').trim().toLowerCase();
  return SHA256_PATTERN.test(digest) ? `sha256:${digest}` : '';
}

export async function openStorageFileFromDeviceCache(
  file: StorageFile,
  options: StorageFileCacheClientOptions = {},
): Promise<Blob | null> {
  const fileId = String(file.file_id || file.id || '').trim();
  const sourceVersion = stableStorageFileSourceVersion(file);
  const maxBytes = boundedMaximum(options.maxBytes);
  if (!fileId || !sourceVersion
      || !Number.isSafeInteger(file.size_bytes)
      || file.size_bytes < 0
      || file.size_bytes > maxBytes) return null;
  const result = await (options.request ?? requestParentFileCacheOpen)({
    fileId,
    sourceVersion,
  }, { signal: options.signal });
  return result?.blob ?? null;
}

function boundedMaximum(value: number | undefined): number {
  if (value === undefined) return MAX_DEVICE_FILE_CACHE_ENTRY_BYTES;
  return Number.isSafeInteger(value) && value >= 0
    ? Math.min(value, MAX_DEVICE_FILE_CACHE_ENTRY_BYTES)
    : 0;
}
