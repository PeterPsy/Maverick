import { IndexedDbCacheBackend } from "./indexedDbBackend";
import { MemoryCacheBackend } from "./memoryBackend";
import type { CacheBackend, CacheEntryMetadata, CacheFilter, StoredCacheEntry } from "./types";

export class ResilientCacheBackend implements CacheBackend {
  private active: CacheBackend;
  private readonly fallback: CacheBackend;
  private readonly onFailure?: (error: unknown) => void;

  constructor(primary?: CacheBackend, options: { fallback?: CacheBackend; onFailure?: (error: unknown) => void } = {}) {
    this.fallback = options.fallback ?? new MemoryCacheBackend();
    this.onFailure = options.onFailure;
    this.active = primary ?? createIndexedDbBackend(this.fallback);
  }

  mode(): "indexeddb" | "memory" {
    return this.active.mode();
  }

  async initialize(): Promise<void> {
    await this.invoke((backend) => backend.initialize());
  }

  async get<T>(key: string): Promise<StoredCacheEntry<T> | null> {
    return this.invoke((backend) => backend.get<T>(key));
  }

  async put<T>(entry: StoredCacheEntry<T>): Promise<void> {
    await this.invoke((backend) => backend.put(entry));
  }

  async touch(
    key: string,
    patch: Partial<Pick<CacheEntryMetadata,
      "accessLeaseExpiresAt" | "cachedAt" | "etag" | "expiresAt" | "lastAccessedAt" | "revision" | "staleAt"
    >>,
  ): Promise<boolean> {
    return this.invoke((backend) => backend.touch(key, patch));
  }

  async delete(key: string): Promise<boolean> {
    return this.invoke((backend) => backend.delete(key));
  }

  async list(filter: CacheFilter = {}): Promise<CacheEntryMetadata[]> {
    return this.invoke((backend) => backend.list(filter));
  }

  async clear(filter: CacheFilter = {}, options: { durable?: boolean } = {}): Promise<number> {
    return this.invoke((backend) => backend.clear(filter, options));
  }

  async pendingCleanupCount(): Promise<number> {
    return this.invoke((backend) => backend.pendingCleanupCount());
  }

  private async invoke<T>(operation: (backend: CacheBackend) => Promise<T>): Promise<T> {
    try {
      return await operation(this.active);
    } catch (error) {
      if (this.active === this.fallback) {
        throw error;
      }
      this.onFailure?.(error);
      this.active = this.fallback;
      await this.fallback.initialize();
      return operation(this.fallback);
    }
  }
}

function createIndexedDbBackend(fallback: CacheBackend): CacheBackend {
  try {
    return new IndexedDbCacheBackend();
  } catch {
    return fallback;
  }
}
