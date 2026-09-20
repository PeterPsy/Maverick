import { readMaverickAppFrameContext } from '@maverick/pwa-cache';
import { decodeBase64, previewDriveFile, readPreviewTable, readPreviewText, renderPreview, renderThumbnail, storageMediaStreamUrl } from './storageApi';
import { openStorageFileFromDeviceCache } from './storageFileCacheClient';
import { PreviewMemoryCache, type PreviewLease, type PreviewValue } from './lib/previewMemoryCache';
import { schedulePreviewConversion } from './lib/previewConversions';
import type { StorageFile } from './types';

const MAX_PREVIEW_ENTRY_BYTES = 8 * 1024 * 1024;
const FULL_TEXT_BYTES = 100 * 1024 * 1024;
const cache = new PreviewMemoryCache();
const pending = new Set<AbortController>();
let scope = '';
export type CachedPreview = PreviewLease;

export function clearPreviewCache(): void {
  for (const controller of pending) controller.abort();
  pending.clear();
  cache.clear();
}

// Frame identity changes remount the realm; BFCache must not retain private previews either.
if (typeof window !== 'undefined') window.addEventListener('pagehide', clearPreviewCache);

function previewKey(file: StorageFile, kind: 'card' | 'full') {
  const currentScope = JSON.stringify(readMaverickAppFrameContext());
  if (scope !== currentScope) { clearPreviewCache(); scope = currentScope; }
  return JSON.stringify([scope, kind, file.provider, file.connection_id, file.id, file.modified_at,
    file.size_bytes, file.preview_kind, file.sha256, file.etag_or_version || file.source_version]);
}

async function cachedFilePreview(file: StorageFile, signal: AbortSignal): Promise<PreviewValue | null> {
  if (!['image', 'pdf', 'text', 'markdown'].includes(file.preview_kind) || file.size_bytes > MAX_PREVIEW_ENTRY_BYTES) return null;
  const blob = await openStorageFileFromDeviceCache(file, { maxBytes: MAX_PREVIEW_ENTRY_BYTES, signal });
  signal.throwIfAborted();
  if (!blob) return null;
  if (['text', 'markdown'].includes(file.preview_kind)) {
    const text = await blob.text();
    signal.throwIfAborted();
    return { text, url: '' };
  }
  return { text: '', url: URL.createObjectURL(blob), bytes: blob.size };
}

async function renderedPreview(file: StorageFile, kind: 'card' | 'full', signal: AbortSignal): Promise<PreviewValue> {
  try {
    return await schedulePreviewConversion(async () => {
      signal.throwIfAborted();
      const payload = await (kind === 'card' ? renderThumbnail : renderPreview)(file, { signal });
      signal.throwIfAborted();
      if (!payload.stream_url) throw new Error('The rendered preview stream is unavailable.');
      return { text: '', url: payload.stream_url };
    }, signal);
  } catch (error) {
    signal.throwIfAborted();
    const payload = await readPreviewText(file, kind === 'card' ? 1200 : undefined, { signal });
    return { text: payload.preview_text, url: '' };
  }
}

async function localText(file: StorageFile, kind: 'card' | 'full', signal: AbortSignal): Promise<PreviewValue> {
  if (kind === 'card') {
    const payload = await readPreviewText(file, 1600, { signal });
    return { text: payload.preview_text, url: '' };
  }
  if (file.size_bytes > FULL_TEXT_BYTES) throw new Error('This file is too large for a text preview.');
  const response = await fetch(storageMediaStreamUrl(file), { credentials: 'same-origin', signal });
  if (!response.ok) throw new Error('Unable to read the file preview.');
  const reader = response.body?.getReader();
  if (!reader) return { text: '', url: '' };
  const decoder = new TextDecoder();
  const parts: string[] = [];
  let bytes = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > FULL_TEXT_BYTES) {
        await reader.cancel();
        throw new Error('This file is too large for a text preview.');
      }
      parts.push(decoder.decode(value, { stream: true }));
    }
    parts.push(decoder.decode());
    return { text: parts.join(''), url: '' };
  } finally { reader.releaseLock(); }
}

async function loadValue(file: StorageFile, kind: 'card' | 'full', signal: AbortSignal): Promise<PreviewValue> {
  if (['image', 'pdf', 'video', 'audio'].includes(file.preview_kind)) {
    if (!['video', 'audio'].includes(file.preview_kind)) {
      const cached = await cachedFilePreview(file, signal);
      if (cached) return cached;
    }
    return { text: '', url: storageMediaStreamUrl(file) };
  }
  if (file.provider === 'google_drive') {
    const payload = await previewDriveFile(file, MAX_PREVIEW_ENTRY_BYTES, kind === 'card' ? 1600 : undefined, { signal });
    signal.throwIfAborted();
    if ('preview_text' in payload) return { text: payload.preview_text || '', url: '' };
    if (!payload.content_base64) return { text: '', url: '' };
    const blob = decodeBase64(payload.content_base64, payload.content_type || payload.file.content_type);
    if (['text', 'markdown'].includes(file.preview_kind)) return { text: await blob.text(), url: '' };
    return { text: '', url: URL.createObjectURL(blob), bytes: blob.size };
  }
  if (file.preview_kind === 'spreadsheet' || file.extension.toLowerCase() === '.csv') {
    const table = await readPreviewTable(file, kind === 'card' ? 8 : undefined, kind === 'card' ? 6 : undefined, { signal });
    return { text: '', url: '', table };
  }
  if (['document', 'presentation'].includes(file.preview_kind)) return renderedPreview(file, kind, signal);
  if (['text', 'markdown'].includes(file.preview_kind)) {
    const cached = await cachedFilePreview(file, signal);
    return cached ?? localText(file, kind, signal);
  }
  const payload = await readPreviewText(file, kind === 'card' ? 1200 : undefined, { signal });
  return { text: payload.preview_text, url: '' };
}

async function load(file: StorageFile, kind: 'card' | 'full', signal?: AbortSignal): Promise<PreviewLease> {
  signal?.throwIfAborted();
  const key = previewKey(file, kind);
  const cached = cache.get(key, signal);
  if (cached) return cached;
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  signal?.addEventListener('abort', abort, { once: true });
  pending.add(controller);
  try {
    const value = await loadValue(file, kind, controller.signal);
    if (controller.signal.aborted) {
      if (value.url.startsWith('blob:')) URL.revokeObjectURL(value.url);
      controller.signal.throwIfAborted();
    }
    return cache.remember(key, value, signal);
  } finally {
    pending.delete(controller);
    signal?.removeEventListener('abort', abort);
  }
}

export function loadCardPreview(file: StorageFile, signal?: AbortSignal) { return load(file, 'card', signal); }
export function loadFullPreview(file: StorageFile, signal?: AbortSignal) { return load(file, 'full', signal); }
