import type { CacheFilter } from "./types";

const STORAGE_KEY = "maverick-pwa-cache-cleanup-barrier-v1";
const inMemoryRecords = new Map<string, BarrierRecord>();
const memoryOnlyIds = new Set<string>();

type BarrierRecord = {
  backendKey: string;
  filter: CacheFilter;
  id: string;
};

export function markCleanupPending(backendKey: string, filter: CacheFilter): void {
  hydrate();
  const normalizedFilter = structuredClone(filter);
  const id = JSON.stringify([backendKey, normalizedFilter]);
  inMemoryRecords.set(id, { backendKey, filter: normalizedFilter, id });
  memoryOnlyIds.add(id);
  persist();
}

export function resolveCoveredCleanups(backendKey: string, clearedFilter: CacheFilter): void {
  hydrate();
  for (const [id, record] of inMemoryRecords) {
    if (record.backendKey === backendKey && filterCovers(clearedFilter, record.filter)) {
      inMemoryRecords.delete(id);
      memoryOnlyIds.delete(id);
    }
  }
  persist();
}

export function pendingCleanupFilters(backendKey: string): CacheFilter[] {
  hydrate();
  return Array.from(inMemoryRecords.values())
    .filter((record) => record.backendKey === backendKey)
    .map((record) => structuredClone(record.filter));
}

function hydrate(): void {
  const storage = browserStorage();
  if (!storage) {
    return;
  }
  try {
    const value = JSON.parse(storage.getItem(STORAGE_KEY) || "[]") as unknown;
    if (!Array.isArray(value)) {
      return;
    }
    const persistedIds = new Set<string>();
    for (const candidate of value) {
      if (!isBarrierRecord(candidate)) {
        continue;
      }
      inMemoryRecords.set(candidate.id, candidate);
      persistedIds.add(candidate.id);
    }
    for (const id of inMemoryRecords.keys()) {
      if (!persistedIds.has(id) && !memoryOnlyIds.has(id)) {
        inMemoryRecords.delete(id);
      }
    }
  } catch {
    // The in-memory barrier remains authoritative for the current document.
  }
}

function persist(): void {
  const storage = browserStorage();
  if (!storage) {
    return;
  }
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(Array.from(inMemoryRecords.values())));
    memoryOnlyIds.clear();
  } catch {
    // IndexedDB's own cleanup marker remains the durable fallback.
  }
}

function browserStorage(): Storage | null {
  try {
    return typeof globalThis.localStorage === "undefined" ? null : globalThis.localStorage;
  } catch {
    return null;
  }
}

function isBarrierRecord(value: unknown): value is BarrierRecord {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Partial<BarrierRecord>;
  return typeof candidate.backendKey === "string"
    && candidate.backendKey.length > 0
    && typeof candidate.id === "string"
    && candidate.id.length > 0
    && Boolean(candidate.filter)
    && typeof candidate.filter === "object";
}

function filterCovers(cleared: CacheFilter, pending: CacheFilter): boolean {
  for (const [key, value] of Object.entries(cleared)) {
    if (pending[key as keyof CacheFilter] !== value) {
      return false;
    }
  }
  return true;
}
