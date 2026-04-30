import { decodeBase64, readFile, readPreviewTable, readPreviewText, renderPreview, renderThumbnail } from './galleryApi';
import type { GalleryFile, PreviewTablePayload } from './types';

const MAX_CACHE_ENTRIES = 80;
const CARD_PREVIEW_BYTES = 8 * 1024 * 1024;
const FULL_PREVIEW_BYTES = 100 * 1024 * 1024;
const TEXT_CARD_CHARS = 1600;
const DOCUMENT_CARD_CHARS = 1200;
const TABLE_CARD_ROWS = 8;
const TABLE_CARD_COLUMNS = 6;

export type CachedPreview = {
  text: string;
  url: string;
  table?: PreviewTablePayload;
};

type CacheEntry = {
  promise: Promise<CachedPreview>;
  url: string;
  lastUsedAt: number;
};

const cache = new Map<string, CacheEntry>();

function canInlinePreview(file: GalleryFile) {
  return ['image', 'video', 'audio', 'text', 'markdown', 'pdf'].includes(file.preview_kind);
}

function canRenderedPreview(file: GalleryFile) {
  return ['pdf', 'document', 'presentation', 'spreadsheet'].includes(file.preview_kind);
}

function canTablePreview(file: GalleryFile) {
  return file.preview_kind === 'spreadsheet' || file.extension.toLowerCase() === '.csv';
}

function previewKey(file: GalleryFile, scope: 'card' | 'full') {
  return [scope, file.id, file.modified_at, file.size_bytes, file.preview_kind].join(':');
}

function remember(key: string, promise: Promise<CachedPreview>) {
  const entry: CacheEntry = { promise, url: '', lastUsedAt: Date.now() };
  cache.set(key, entry);
  promise.then((preview) => {
    entry.url = preview.url;
  });
  pruneCache();
  return promise;
}

function pruneCache() {
  if (cache.size <= MAX_CACHE_ENTRIES) return;
  const staleEntries = [...cache.entries()].sort((left, right) => left[1].lastUsedAt - right[1].lastUsedAt);
  for (const [key, entry] of staleEntries.slice(0, cache.size - MAX_CACHE_ENTRIES)) {
    if (entry.url) URL.revokeObjectURL(entry.url);
    cache.delete(key);
  }
}

function getCachedPreview(key: string) {
  const entry = cache.get(key);
  if (!entry) return null;
  entry.lastUsedAt = Date.now();
  return entry.promise;
}

function blobPreview(file: GalleryFile, maxBytes: number, textLimit?: number) {
  return readFile(file, maxBytes).then((payload) => {
    const blob = decodeBase64(payload.content_base64, payload.file.content_type);
    if (['text', 'markdown'].includes(payload.file.preview_kind)) {
      return blob.text().then((text) => ({ text: textLimit === undefined ? text : text.slice(0, textLimit), url: '' }));
    }
    return { text: '', url: URL.createObjectURL(blob) };
  });
}

function renderedDocumentPreview(file: GalleryFile, scope: 'card' | 'full') {
  const renderer = scope === 'card' && ['document', 'presentation', 'spreadsheet'].includes(file.preview_kind)
    ? renderThumbnail
    : renderPreview;
  return renderer(file).then((payload) => {
    const blob = decodeBase64(payload.content_base64, payload.content_type);
    return { text: '', url: URL.createObjectURL(blob) };
  }).catch((error) => {
    if (['document', 'presentation', 'spreadsheet'].includes(file.preview_kind)) {
      return readPreviewText(file, scope === 'card' ? DOCUMENT_CARD_CHARS : undefined).then((payload) => ({ text: payload.preview_text, url: '' }));
    }
    throw error;
  });
}

function tablePreview(file: GalleryFile, scope: 'card' | 'full') {
  if (scope === 'card') {
    return readPreviewTable(file, TABLE_CARD_ROWS, TABLE_CARD_COLUMNS).then((table) => ({ text: '', url: '', table }));
  }
  return readPreviewTable(file).then((table) => ({ text: '', url: '', table }));
}

export function loadCardPreview(file: GalleryFile) {
  const key = previewKey(file, 'card');
  const cached = getCachedPreview(key);
  if (cached) return cached;
  if (file.preview_kind === 'audio') return remember(key, Promise.resolve({ text: '', url: '' }));
  if (canTablePreview(file)) return remember(key, tablePreview(file, 'card'));
  if (canRenderedPreview(file)) return remember(key, renderedDocumentPreview(file, 'card'));
  if (canInlinePreview(file)) return remember(key, blobPreview(file, CARD_PREVIEW_BYTES, TEXT_CARD_CHARS));
  return remember(key, readPreviewText(file, DOCUMENT_CARD_CHARS).then((payload) => ({ text: payload.preview_text, url: '' })));
}

export function loadFullPreview(file: GalleryFile) {
  const key = previewKey(file, 'full');
  const cached = getCachedPreview(key);
  if (cached) return cached;
  if (canTablePreview(file)) return remember(key, tablePreview(file, 'full'));
  if (canRenderedPreview(file)) return remember(key, renderedDocumentPreview(file, 'full'));
  if (canInlinePreview(file)) return remember(key, blobPreview(file, FULL_PREVIEW_BYTES));
  return remember(key, readPreviewText(file).then((payload) => ({ text: payload.preview_text, url: '' })));
}
