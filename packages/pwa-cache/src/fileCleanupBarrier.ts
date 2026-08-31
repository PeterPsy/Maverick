import type { FileCacheFilter } from "./fileCacheTypes";

const STORAGE_KEY = "maverick-pwa-file-cache-cleanup-barrier-v1";
const records = new Map<string, BarrierRecord>();
const memoryOnlyIds = new Set<string>();

type BarrierRecord = {
  filter: FileCacheFilter;
  id: string;
};

export function markFileCacheCleanupPending(filter: FileCacheFilter): void {
  hydrate();
  const normalized = structuredClone(filter);
  const id = JSON.stringify(normalized);
  records.set(id, { filter: normalized, id });
  memoryOnlyIds.add(id);
  persist();
}

export function resolveFileCacheCleanup(filter: FileCacheFilter): void {
  hydrate();
  for (const [id, record] of records) {
    if (filterCovers(filter, record.filter)) {
      records.delete(id);
      memoryOnlyIds.delete(id);
    }
  }
  persist();
}

export function pendingFileCacheCleanupFilters(): FileCacheFilter[] {
  hydrate();
  return Array.from(records.values(), (record) => structuredClone(record.filter));
}

function hydrate(): void {
  const storage = browserStorage();
  if (!storage) return;
  try {
    const value = JSON.parse(storage.getItem(STORAGE_KEY) || "[]") as unknown;
    if (!Array.isArray(value)) return;
    const persisted = new Set<string>();
    for (const candidate of value) {
      if (!isBarrierRecord(candidate)) continue;
      records.set(candidate.id, candidate);
      persisted.add(candidate.id);
    }
    for (const id of records.keys()) {
      if (!persisted.has(id) && !memoryOnlyIds.has(id)) records.delete(id);
    }
  } catch {
    // The current-document barrier still prevents reuse.
  }
}

function persist(): void {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(Array.from(records.values())));
    memoryOnlyIds.clear();
  } catch {
    // IndexedDB's manifest marker remains the durable fallback.
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
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<BarrierRecord>;
  return typeof record.id === "string" && Boolean(record.filter) && typeof record.filter === "object";
}

function filterCovers(cleared: FileCacheFilter, pending: FileCacheFilter): boolean {
  return Object.entries(cleared).every(([key, value]) => pending[key as keyof FileCacheFilter] === value);
}
