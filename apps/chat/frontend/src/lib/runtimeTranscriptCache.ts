import type { RuntimeEvent, RuntimeSession, RuntimeTurn } from "../api/client";

export type RuntimeTranscriptCacheEntry = {
  activeSession: RuntimeSession | null;
  activeTurn: RuntimeTurn | null;
  events: RuntimeEvent[];
  hasLoadedHistory: boolean;
  hasMoreHistory?: boolean;
};

type TranscriptStorage = Pick<Storage, "getItem" | "removeItem" | "setItem">;

const STORAGE_KEY_PREFIX = "maverick.chat.runtime-transcript-cache.v1:";
const MAX_CACHED_EVENTS = 300;

export function normalizeRuntimeTranscriptCacheEntry(entry: RuntimeTranscriptCacheEntry): RuntimeTranscriptCacheEntry {
  const events = entry.events.slice(-MAX_CACHED_EVENTS);
  return {
    activeSession: entry.activeSession,
    activeTurn: entry.activeTurn,
    events,
    hasLoadedHistory: entry.hasLoadedHistory || events.length > 0,
    hasMoreHistory: entry.hasMoreHistory === true,
  };
}

export function readStoredRuntimeTranscript(runtimeSessionId: string, storage = defaultTranscriptStorage()): RuntimeTranscriptCacheEntry | null {
  if (!runtimeSessionId || !storage) {
    return null;
  }
  try {
    const raw = storage.getItem(storageKey(runtimeSessionId));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<RuntimeTranscriptCacheEntry>;
    if (!parsed || !Array.isArray(parsed.events)) {
      storage.removeItem(storageKey(runtimeSessionId));
      return null;
    }
    return normalizeRuntimeTranscriptCacheEntry({
      activeSession: parsed.activeSession || null,
      activeTurn: parsed.activeTurn || null,
      events: parsed.events,
      hasLoadedHistory: parsed.hasLoadedHistory === true,
      hasMoreHistory: parsed.hasMoreHistory === true,
    });
  } catch {
    storage.removeItem(storageKey(runtimeSessionId));
    return null;
  }
}

export function writeStoredRuntimeTranscript(
  runtimeSessionId: string,
  entry: RuntimeTranscriptCacheEntry,
  storage = defaultTranscriptStorage(),
) {
  if (!runtimeSessionId || !storage) {
    return;
  }
  try {
    storage.setItem(storageKey(runtimeSessionId), JSON.stringify(normalizeRuntimeTranscriptCacheEntry(entry)));
  } catch {
    // Cache writes are best-effort; quota or privacy failures must not affect chat.
  }
}

export function deleteStoredRuntimeTranscript(runtimeSessionId: string, storage = defaultTranscriptStorage()) {
  if (!runtimeSessionId || !storage) {
    return;
  }
  try {
    storage.removeItem(storageKey(runtimeSessionId));
  } catch {
    // Cache deletes are best-effort for the same reason writes are.
  }
}

function storageKey(runtimeSessionId: string) {
  return `${STORAGE_KEY_PREFIX}${runtimeSessionId}`;
}

function defaultTranscriptStorage(): TranscriptStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}
