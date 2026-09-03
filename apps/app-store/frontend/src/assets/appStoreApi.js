import { readThroughParentDataCache } from '@maverick/pwa-cache';
import { sanitizeCatalog } from './catalogReadModel.js';

export async function requestJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    const transport = new Error('App Store transport failed.', { cause: error });
    transport.name = 'MaverickTransportError';
    throw transport;
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    if (response.ok) throw new TypeError('App Store returned an invalid JSON response.', { cause: error });
  }
  if (!response.ok) {
    const detail = payload.detail || payload.error || `HTTP ${response.status}`;
    throw new AppStoreHttpError(detail, response);
  }
  return payload;
}

export async function loadCachedCatalog() {
  return readThroughParentDataCache({
    appId: 'app-store',
    entityId: 'visible-public-catalog',
    resource: 'catalog',
    schemaRevision: 'app-store.catalog.v1'
  }, async ({ etag, signal }) => {
    let response;
    try {
      response = await fetch('/api/app-store/apps', {
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          ...(etag ? { 'If-None-Match': etag } : {})
        },
        signal
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      const transport = new Error('App Store catalog transport failed.', { cause: error });
      transport.name = 'MaverickTransportError';
      throw transport;
    }
    const responseEtag = response.headers.get('etag') || etag || undefined;
    if (response.status === 304) {
      if (!etag || responseEtag !== etag) {
        throw new TypeError('App Store returned 304 without the requested validator.');
      }
      return { kind: 'not_modified', etag: responseEtag };
    }
    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      if (response.ok) throw new TypeError('App Store returned an invalid catalog response.', { cause: error });
    }
    if (!response.ok) {
      throw new AppStoreHttpError(payload.detail || payload.error || `HTTP ${response.status}`, response);
    }
    const sanitized = sanitizeCatalog(payload);
    if (!sanitized) throw new TypeError('App Store returned an invalid catalog read model.');
    return {
      kind: 'value',
      payload: sanitized,
      revision: sanitized.revision,
      ...(responseEtag ? { etag: responseEtag } : {})
    };
  }, { sanitize: sanitizeCatalog });
}

export class AppStoreHttpError extends Error {
  constructor(message, response) {
    super(message);
    this.name = 'MaverickHttpError';
    this.status = response.status;
    this.retryAfterMs = parseRetryAfter(response.headers.get('retry-after'));
  }
}

function parseRetryAfter(value) {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 60000);
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? Math.max(0, Math.min(timestamp - Date.now(), 60000)) : null;
}
