import { advancePublicationGeneration, withPublicationLock } from "./publicationBarrier";
import { IndexedDbCacheBackend } from "./indexedDbBackend";
import { MemoryCacheBackend } from "./memoryBackend";
import { markCleanupPending, pendingCleanupFilters, resolveCoveredCleanups } from "./cleanupBarrier";
import type { CacheBackend, CacheEntryMetadata, CacheFilter, StoredCacheEntry } from "./types";

export class DurableCacheCleanupError extends Error {
  readonly pending = true;

  constructor(options?: ErrorOptions) {
    super("Durable PWA cache cleanup is pending and persistent cache access is blocked.", options);
    this.name = "DurableCacheCleanupError";
  }
}

export class ResilientCacheBackend implements CacheBackend {
  private active: CacheBackend;
  private readonly fallback: CacheBackend;
  private readonly onFailure?: (error: unknown) => void;
  private readonly primary: CacheBackend;
  private readonly primaryDurabilityKey: string;

  constructor(primary?: CacheBackend, options: { fallback?: CacheBackend; onFailure?: (error: unknown) => void } = {}) {
    this.fallback = options.fallback ?? new MemoryCacheBackend();
    this.onFailure = options.onFailure;
    this.primary = primary ?? createIndexedDbBackend(this.fallback);
    this.primaryDurabilityKey = this.primary.durabilityKey();
    this.active = this.primary;
  }

  mode(): "indexeddb" | "memory" {
    return this.active.mode();
  }

  durabilityMode(): "indexeddb" | "memory" {
    return this.primary.durabilityMode();
  }

  durabilityKey(): string {
    return this.primaryDurabilityKey;
  }

  async initialize(): Promise<void> {
    await this.invoke((backend) => backend.initialize());
    for (const filter of pendingCleanupFilters(this.primaryDurabilityKey)) {
      try {
        await this.clear(filter, { durable: true });
      } catch {
        break;
      }
    }
  }

  async get<T>(key: string): Promise<StoredCacheEntry<T> | null> {
    if (this.cleanupBlocked()) {
      return null;
    }
    return this.invoke((backend) => backend.get<T>(key));
  }

  async put<T>(entry: StoredCacheEntry<T>): Promise<void> {
    this.throwIfCleanupBlocked();
    await this.invoke((backend) => backend.put(entry));
  }

  async touch(
    key: string,
    patch: Partial<Pick<CacheEntryMetadata,
      "accessLeaseExpiresAt" | "cachedAt" | "etag" | "expiresAt" | "lastAccessedAt" | "revision" | "staleAt"
    >>,
  ): Promise<boolean> {
    if (this.cleanupBlocked()) {
      return false;
    }
    return this.invoke((backend) => backend.touch(key, patch));
  }

  async delete(key: string): Promise<boolean> {
    if (this.cleanupBlocked()) {
      return false;
    }
    return this.invoke((backend) => backend.delete(key));
  }

  async list(filter: CacheFilter = {}): Promise<CacheEntryMetadata[]> {
    if (this.cleanupBlocked()) {
      return [];
    }
    return this.invoke((backend) => backend.list(filter));
  }

  async clear(filter: CacheFilter = {}, options: { durable?: boolean } = {}): Promise<number> {
    return this.clearWithPublication(filter, options, false);
  }

  async clearForMaintenance(filter: CacheFilter, options: { durable?: boolean }): Promise<number> {
    return this.clearWithPublication(filter, options, true);
  }

  private async clearWithPublication(filter: CacheFilter, options: { durable?: boolean }, maintenance: boolean): Promise<number> {
    return withPublicationLock(this.primaryDurabilityKey, async () => {
      if (options.durable) markCleanupPending(this.primaryDurabilityKey, filter);
      advancePublicationGeneration(this.primaryDurabilityKey, this.durabilityMode() === "indexeddb", maintenance);
      if (options.durable) return this.clearDurably(filter);
      return this.invoke((backend) => backend.clear(filter, options));
    });
  }

  async pendingCleanupCount(): Promise<number> {
    const barrierCount = pendingCleanupFilters(this.primaryDurabilityKey).length;
    try {
      return Math.max(barrierCount, await this.primary.pendingCleanupCount());
    } catch {
      return Math.max(barrierCount, await this.fallback.pendingCleanupCount().catch(() => 0));
    }
  }

  private async clearDurably(filter: CacheFilter): Promise<number> {
    markCleanupPending(this.primaryDurabilityKey, filter);
    let fallbackRemoved = 0;
    if (this.primary !== this.fallback) {
      fallbackRemoved = await this.fallback.clear(filter).catch(() => 0);
    }
    try {
      const removed = await this.primary.clear(filter, { durable: true });
      resolveCoveredCleanups(this.primaryDurabilityKey, filter);
      this.active = this.primary;
      return removed + fallbackRemoved;
    } catch (error) {
      this.onFailure?.(error);
      this.active = this.fallback;
      await this.fallback.initialize().catch(() => undefined);
      throw new DurableCacheCleanupError({ cause: error });
    }
  }

  private cleanupBlocked(): boolean {
    return pendingCleanupFilters(this.primaryDurabilityKey).length > 0;
  }

  private throwIfCleanupBlocked(): void {
    if (this.cleanupBlocked()) {
      throw new DurableCacheCleanupError();
    }
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
