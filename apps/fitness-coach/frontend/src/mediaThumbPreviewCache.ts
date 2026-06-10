import { currentStorageAppId } from './api';
import { mediaCacheKey } from './mediaPlaybackResolver';
import type { ExerciseMediaRef } from './types';

const THUMB_PREVIEW_STORAGE_KEY = 'fitness-coach:media-thumb-preview:v1';
const THUMB_PREVIEW_CACHE_LIMIT = 48;
const THUMB_PREVIEW_MAX_WIDTH = 192;

type ThumbPreviewEntry = {
  key: string;
  dataUrl: string;
  updatedAt: number;
};

const memoryCache = new Map<string, ThumbPreviewEntry>();
let hydrated = false;

export function mediaThumbPreviewFrameKey(media: ExerciseMediaRef, storageAppId = currentStorageAppId()) {
  return mediaCacheKey(media, storageAppId, 'thumb-frame');
}

export function readMediaThumbPreviewFrame(key: string): string {
  hydrateThumbPreviewCache();
  return memoryCache.get(key)?.dataUrl || '';
}

export function writeMediaThumbPreviewFrame(key: string, dataUrl: string) {
  if (!key || !isSupportedThumbDataUrl(dataUrl)) return;
  hydrateThumbPreviewCache();
  memoryCache.set(key, { key, dataUrl, updatedAt: Date.now() });
  trimThumbPreviewCache();
  persistThumbPreviewCache();
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
  memoryCache.clear();
  hydrated = false;
  if (options.storage === false) return;
  storage()?.removeItem(THUMB_PREVIEW_STORAGE_KEY);
}

function hydrateThumbPreviewCache() {
  if (hydrated) return;
  hydrated = true;
  const payload = storage()?.getItem(THUMB_PREVIEW_STORAGE_KEY);
  if (!payload) return;
  try {
    const parsed = JSON.parse(payload) as { entries?: ThumbPreviewEntry[] };
    parsed.entries?.forEach((entry) => {
      if (entry?.key && isSupportedThumbDataUrl(entry.dataUrl)) {
        memoryCache.set(entry.key, {
          key: entry.key,
          dataUrl: entry.dataUrl,
          updatedAt: Number(entry.updatedAt) || 0
        });
      }
    });
    trimThumbPreviewCache();
  } catch {
    memoryCache.clear();
  }
}

function persistThumbPreviewCache() {
  const target = storage();
  if (!target) return;
  try {
    target.setItem(THUMB_PREVIEW_STORAGE_KEY, JSON.stringify({ entries: orderedEntries() }));
  } catch {
    const entries = orderedEntries();
    while (entries.length > 0) {
      entries.shift();
      try {
        target.setItem(THUMB_PREVIEW_STORAGE_KEY, JSON.stringify({ entries }));
        break;
      } catch {
        // Keep trimming until the browser accepts the smaller cache payload.
      }
    }
  }
}

function trimThumbPreviewCache() {
  const entries = orderedEntries();
  entries.slice(0, Math.max(0, entries.length - THUMB_PREVIEW_CACHE_LIMIT)).forEach((entry) => {
    memoryCache.delete(entry.key);
  });
}

function orderedEntries() {
  return Array.from(memoryCache.values()).sort((first, second) => first.updatedAt - second.updatedAt);
}

function isSupportedThumbDataUrl(dataUrl: string | undefined) {
  return /^data:image\/(?:jpeg|png|webp);base64,/i.test(String(dataUrl || ''));
}

function storage(): Storage | null {
  try {
    return typeof globalThis.sessionStorage === 'undefined' ? null : globalThis.sessionStorage;
  } catch {
    return null;
  }
}
