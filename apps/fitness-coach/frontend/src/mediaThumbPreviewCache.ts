import { createRequestFingerprint, readThroughParentDataCache } from '@maverick/pwa-cache';
import { currentStorageAppId, mountedAppIdFromPath } from './api';
import { mediaCacheKey } from './mediaPlaybackResolver';
import type { ExerciseMediaRef } from './types';

const THUMB_PREVIEW_STORAGE_KEY = 'fitness-coach:media-thumb-preview:v1';
const THUMB_PREVIEW_CACHE_LIMIT = 48;
const THUMB_PREVIEW_MAX_WIDTH = 192;
const THUMB_PREVIEW_MAX_DATA_URL_CHARS = 480_000;
export const THUMB_PREVIEW_CACHE_CHANGED_EVENT = 'maverick.fitness.thumb-cache-changed';

type ThumbPreviewEntry = {
  key: string;
  dataUrl: string;
  updatedAt: number;
};

type PendingBrokerRead = {
  controller: AbortController;
  promise: Promise<void>;
};

// Only parent-broker results and frames captured in this page are renderable.
// Old sessionStorage values remain quarantined as migration seeds until the
// parent confirms that they were committed into its authenticated scope.
const memoryCache = new Map<string, ThumbPreviewEntry>();
const legacySeeds = new Map<string, ThumbPreviewEntry>();
const pendingBrokerReads = new Map<string, PendingBrokerRead>();
let hydrated = false;
let generation = 0;

export function mediaThumbPreviewFrameKey(media: ExerciseMediaRef, storageAppId = currentStorageAppId()) {
  return mediaCacheKey(media, storageAppId, 'thumb-frame');
}

export function readMediaThumbPreviewFrame(key: string): string {
  hydrateLegacyThumbPreviewSeeds();
  if (hasStableThumbIdentity(key) && !memoryCache.has(key)) {
    void brokerThumb(key, legacySeeds.get(key) || null);
  }
  return memoryCache.get(key)?.dataUrl || '';
}

export function writeMediaThumbPreviewFrame(key: string, dataUrl: string) {
  const entry = sanitizeThumbPreviewEntry({ key, dataUrl, updatedAt: Date.now() });
  if (!entry) return;
  hydrateLegacyThumbPreviewSeeds();
  memoryCache.set(key, entry);
  trimMemoryCache();
  if (legacySeeds.delete(key)) persistLegacyThumbPreviewSeeds();
  if (hasStableThumbIdentity(key)) void brokerThumb(key, entry, true);
}

export function captureMediaThumbVideoFrame(video: HTMLVideoElement, key: string): string {
  if (!key || readMediaThumbPreviewFrame(key)) return '';
  const width = video.videoWidth || 0;
  const height = video.videoHeight || 0;
  if (width <= 0 || height <= 0) return '';

  try {
    const targetWidth = Math.max(1, Math.min(THUMB_PREVIEW_MAX_WIDTH, width));
    const targetHeight = Math.max(1, Math.round(targetWidth * (height / width)));
    const canvas = document.createElement('canvas');
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const context = canvas.getContext('2d');
    if (!context) return '';
    context.drawImage(video, 0, 0, targetWidth, targetHeight);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.72);
    writeMediaThumbPreviewFrame(key, dataUrl);
    return dataUrl;
  } catch {
    return '';
  }
}

export function clearMediaThumbPreviewFrameCache(options: { storage?: boolean } = {}) {
  generation += 1;
  pendingBrokerReads.forEach(({ controller }) => controller.abort());
  pendingBrokerReads.clear();
  memoryCache.clear();
  legacySeeds.clear();
  hydrated = false;
  if (options.storage === false) return;
  storage()?.removeItem(THUMB_PREVIEW_STORAGE_KEY);
}

function hydrateLegacyThumbPreviewSeeds() {
  if (hydrated) return;
  hydrated = true;
  // This legacy namespace has no user/workspace attestation.
  try { storage()?.removeItem(THUMB_PREVIEW_STORAGE_KEY); } catch { /* best effort */ }
}

function persistLegacyThumbPreviewSeeds() {
  const target = storage();
  if (!target) return;
  try {
    if (!legacySeeds.size) {
      target.removeItem(THUMB_PREVIEW_STORAGE_KEY);
      return;
    }
    target.setItem(THUMB_PREVIEW_STORAGE_KEY, JSON.stringify({ entries: orderedEntries(legacySeeds) }));
  } catch {
    // Migration cleanup is best-effort; legacy values are never rendered here.
  }
}

function trimMemoryCache() {
  trimEntries(memoryCache);
}

function trimLegacySeeds() {
  trimEntries(legacySeeds);
  persistLegacyThumbPreviewSeeds();
}

function trimEntries(entries: Map<string, ThumbPreviewEntry>) {
  orderedEntries(entries)
    .slice(0, Math.max(0, entries.size - THUMB_PREVIEW_CACHE_LIMIT))
    .forEach((entry) => entries.delete(entry.key));
}

function orderedEntries(entries: Map<string, ThumbPreviewEntry>) {
  return Array.from(entries.values()).sort((first, second) => first.updatedAt - second.updatedAt);
}

function isSupportedThumbDataUrl(dataUrl: string | undefined) {
  const normalized = String(dataUrl || '');
  return normalized.length <= THUMB_PREVIEW_MAX_DATA_URL_CHARS
    && /^data:image\/(?:jpeg|png|webp);base64,/i.test(normalized);
}

function hasStableThumbIdentity(key: string): boolean {
  return key.startsWith('thumb-frame:') && !key.endsWith(':');
}

function brokerThumb(
  key: string,
  migrationEntry: ThumbPreviewEntry | null,
  supersede = false
): Promise<void> {
  const existing = pendingBrokerReads.get(key);
  if (existing && !supersede) return existing.promise;
  if (existing) {
    existing.controller.abort();
    pendingBrokerReads.delete(key);
  }
  const controller = new AbortController();
  const startedGeneration = generation;
  let promise!: Promise<void>;
  promise = runBrokeredThumb(key, migrationEntry, controller.signal, startedGeneration)
    .catch(() => undefined)
    .finally(() => {
      if (pendingBrokerReads.get(key)?.promise === promise) pendingBrokerReads.delete(key);
    });
  pendingBrokerReads.set(key, { controller, promise });
  return promise;
}

async function runBrokeredThumb(
  key: string,
  migrationEntry: ThumbPreviewEntry | null,
  signal: AbortSignal,
  startedGeneration: number
) {
  const revision = migrationEntry ? await createRequestFingerprint(migrationEntry.dataUrl) : '';
  const result = await readThroughParentDataCache<ThumbPreviewEntry>({
    appId: mountedAppIdFromPath(typeof window === 'undefined' ? '' : window.location.pathname, 'fitness-coach'),
    entityId: `thumbnail:${key}`,
    ...(migrationEntry ? {
      migrationSeed: { payload: migrationEntry, revision }
    } : {}),
    resource: 'sanitized-bootstrap-and-thumbnails',
    schemaRevision: 'fitness-coach.sanitized-bootstrap-and-thumbnails.v1'
  }, async ({ knownRevision }) => {
    // A broker first persists the migration seed, then revalidates it with the
    // known revision. Direct fallback has no revision and therefore cannot
    // render untrusted legacy storage while the feature is disabled.
    // Existing thumbnails are current because their cache identity already
    // includes the immutable media source version.
    if (knownRevision && (!migrationEntry || knownRevision === revision)) {
      return { kind: 'not_modified', revision: knownRevision } as const;
    }
    if (migrationEntry && knownRevision) {
      return { kind: 'value', payload: migrationEntry, revision } as const;
    }
    const error = new Error('Thumbnail source requires normal media loading.');
    error.name = 'TerminalError';
    throw error;
  }, { sanitize: sanitizeThumbPreviewEntry, signal });

  if (signal.aborted || startedGeneration !== generation) return;
  applyBrokeredThumb(key, result.payload);
  if (result.brokered && migrationEntry && result.migrationCommitted) {
    legacySeeds.delete(key);
    persistLegacyThumbPreviewSeeds();
  }
  if (result.revalidation) {
    const next = await result.revalidation;
    if (!signal.aborted && startedGeneration === generation && next.changed) {
      applyBrokeredThumb(key, next.payload);
    }
  }
}

function applyBrokeredThumb(key: string, payload: ThumbPreviewEntry) {
  if (payload.key !== key) return;
  memoryCache.set(key, payload);
  trimMemoryCache();
  dispatchThumbChanged(key, payload.dataUrl);
}

export function sanitizeThumbPreviewEntry(value: unknown): ThumbPreviewEntry | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const entry = value as Partial<ThumbPreviewEntry>;
  return typeof entry.key === 'string'
      && entry.key.length > 0
      && entry.key.length <= 220
      && isSupportedThumbDataUrl(entry.dataUrl)
      && typeof entry.updatedAt === 'number'
      && Number.isFinite(entry.updatedAt)
      && entry.updatedAt >= 0
    ? { key: entry.key, dataUrl: entry.dataUrl as string, updatedAt: entry.updatedAt }
    : null;
}

function dispatchThumbChanged(key: string, dataUrl: string) {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') return;
  window.dispatchEvent(new CustomEvent(THUMB_PREVIEW_CACHE_CHANGED_EVENT, {
    detail: { key, dataUrl }
  }));
}

function storage(): Storage | null {
  try {
    return typeof globalThis.sessionStorage === 'undefined' ? null : globalThis.sessionStorage;
  } catch {
    return null;
  }
}
