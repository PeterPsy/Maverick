import { matchesFilter } from "./scope";
import type {
  CacheBackend,
  CacheEntryMetadata,
  CacheFilter,
  CleanupMarker,
  StoredCacheEntry,
} from "./types";

export class MemoryCacheBackend implements CacheBackend {
  private static nextId = 0;
  private readonly entries = new Map<string, StoredCacheEntry>();
  private readonly cleanupMarkers = new Map<string, CleanupMarker>();
  private readonly instanceId = ++MemoryCacheBackend.nextId;

  async initialize(): Promise<void> {}

  mode(): "memory" {
    return "memory";
  }

  durabilityMode(): "indexeddb" | "memory" {
    return "memory";
  }

  durabilityKey(): string {
    return `memory:${this.instanceId}`;
  }

  async get<T>(key: string): Promise<StoredCacheEntry<T> | null> {
    const entry = this.entries.get(key);
    return entry ? structuredClone(entry) as StoredCacheEntry<T> : null;
  }

  async put<T>(entry: StoredCacheEntry<T>): Promise<void> {
    this.entries.set(entry.metadata.key, structuredClone(entry));
  }

  async touch(
    key: string,
    patch: Partial<Pick<CacheEntryMetadata,
      "accessLeaseExpiresAt" | "cachedAt" | "etag" | "expiresAt" | "lastAccessedAt" | "revision" | "staleAt"
    >>,
  ): Promise<boolean> {
    const entry = this.entries.get(key);
    if (!entry) {
      return false;
    }
    entry.metadata = { ...entry.metadata, ...patch };
    return true;
  }

  async delete(key: string): Promise<boolean> {
    return this.entries.delete(key);
  }

  async list(filter: CacheFilter = {}): Promise<CacheEntryMetadata[]> {
    return Array.from(this.entries.values())
      .map((entry) => structuredClone(entry.metadata))
      .filter((metadata) => matchesFilter(metadata, filter));
  }

  async clear(filter: CacheFilter = {}, options: { durable?: boolean } = {}): Promise<number> {
    const marker = options.durable ? this.createCleanupMarker(filter) : null;
    let removed = 0;
    for (const [key, entry] of this.entries) {
      if (matchesFilter(entry.metadata, filter)) {
        this.entries.delete(key);
        removed += 1;
      }
    }
    if (marker) {
      this.cleanupMarkers.delete(marker.id);
    }
    return removed;
  }

  async pendingCleanupCount(): Promise<number> {
    return this.cleanupMarkers.size;
  }

  private createCleanupMarker(filter: CacheFilter): CleanupMarker {
    const marker: CleanupMarker = {
      createdAt: Date.now(),
      filter: structuredClone(filter),
      id: randomId(),
      kind: "cleanup",
    };
    this.cleanupMarkers.set(marker.id, marker);
    return marker;
  }
}

function randomId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `cleanup-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
