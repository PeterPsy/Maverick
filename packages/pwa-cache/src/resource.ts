import { publicationGeneration, withPublicationLock } from "./publicationBarrier";
import { enforceCacheBudgets, type CacheBudgets } from "./budget";
import { cacheEntryKey, validateEntityId, validateScope } from "./scope";
import { runSingleFlight } from "./singleFlight";
import { deriveLocalPersistencePolicy, hasValidAccessLease } from "./policy";
import {
  createEntryMetadata,
  isValidEntry,
  resultFromCacheHit,
  safeSanitize,
  type CacheHit,
} from "./resourceEntry";
import { clearResourceBackend, initializeResourceBackends } from "./resourceStorage";
import { validatedPayloadSize } from "./serialization";
import type {
  AccessLease,
  CacheBackend,
  CacheEntryMetadata,
  CacheLoader,
  CacheNetworkResult,
  CacheReadResult,
  CacheRevalidationResult,
  CacheScope,
  CacheTelemetry,
  LocalPersistencePolicy,
  ResourceCachePolicy,
  StorageQuotaAdapter,
} from "./types";

type ResourceOptions<T> = {
  budgets: CacheBudgets;
  enabled: boolean;
  getAccessLease: () => AccessLease | undefined;
  memoryBackend: CacheBackend;
  now: () => number;
  persistentBackend: CacheBackend;
  policy: ResourceCachePolicy<T>;
  quotaAdapter: StorageQuotaAdapter;
  scope: CacheScope;
  telemetry: CacheTelemetry;
};

export class PwaCacheResource<T> {
  readonly persistencePolicy: LocalPersistencePolicy;
  readonly scope: CacheScope;
  private readonly budgets: CacheBudgets;
  private readonly enabled: boolean;
  private readonly getAccessLease: () => AccessLease | undefined;
  private readonly memoryBackend: CacheBackend;
  private readonly now: () => number;
  private readonly persistentBackend: CacheBackend;
  private readonly policy: ResourceCachePolicy<T>;
  private readonly quotaAdapter: StorageQuotaAdapter;
  private readonly telemetry: CacheTelemetry;
  private generation = 0;

  cancelPendingPublications(): void {
    this.generation += 1;
  }

  private initialized: Promise<void> | null = null;

  constructor(options: ResourceOptions<T>) {
    this.scope = validateScope(options.scope);
    this.policy = options.policy;
    this.persistencePolicy = deriveLocalPersistencePolicy(this.scope.appId, this.scope.resource, this.policy);
    this.enabled = options.enabled;
    this.persistentBackend = options.persistentBackend;
    this.memoryBackend = options.memoryBackend;
    this.getAccessLease = options.getAccessLease;
    this.now = options.now;
    this.quotaAdapter = options.quotaAdapter;
    this.budgets = options.budgets;
    this.telemetry = options.telemetry;
  }

  async get(entityId: string): Promise<CacheReadResult<T> | null> {
    const hit = await this.cacheHit(validateEntityId(entityId));
    if (!hit || (hit.freshness === "stale" && this.policy.allowStale !== true)) {
      if (hit) {
        this.telemetry({ kind: "miss", reason: "stale-not-renderable" });
      }
      return null;
    }
    return resultFromCacheHit(hit);
  }

  async readThrough(entityId: string, loader: CacheLoader<T>, signal?: AbortSignal): Promise<CacheReadResult<T>> {
    const generation = this.generation;
    // Schema maintenance precedes admission; the ticket then spans every read,
    // single-flight wait, loader, quota wait and the final publication lock.
    if (this.enabled) await this.initialize().catch(() => undefined);
    const shared = this.persistencePolicy === "cache" && this.persistentBackend.mode() === "indexeddb";
    const publication = publicationGeneration(this.persistentBackend.durabilityKey(), shared);
    const canPublish = () => !signal?.aborted && generation === this.generation
      && publication !== null && publication === publicationGeneration(this.persistentBackend.durabilityKey(), shared);
    const normalizedEntityId = validateEntityId(entityId);
    const hit = await this.cacheHit(normalizedEntityId);
    if (hit && (hit.freshness === "fresh" || this.policy.allowStale === true)) {
      const shouldRevalidate = this.revalidationMode() === "always"
        || (this.revalidationMode() === "stale" && hit.freshness === "stale");
      const revalidation = shouldRevalidate
        ? this.revalidate(normalizedEntityId, loader, hit, canPublish, signal)
        : undefined;
      if (revalidation) {
        void revalidation.catch(() => undefined);
      }
      return { ...resultFromCacheHit(hit), ...(revalidation ? { revalidation } : {}) };
    }
    const network = await this.revalidate(normalizedEntityId, loader, hit, canPublish, signal);
    return {
      freshness: "fresh",
      payload: network.payload,
      revision: network.revision,
      source: "network",
    };
  }

  async invalidate(entityId?: string): Promise<number> {
    this.cancelPendingPublications();
    if (!this.enabled) {
      return 0;
    }
    try {
      await this.initialize();
    } catch (error) {
      this.telemetry({ kind: "error", reason: errorName(error) });
      return 0;
    }
    const filter = {
      ...this.scope,
      ...(entityId ? { entityId: validateEntityId(entityId) } : {}),
    };
    const removed = await Promise.all([
      clearResourceBackend(this.persistentBackend, filter, this.telemetry, true),
      clearResourceBackend(this.memoryBackend, filter, this.telemetry),
    ]);
    return removed[0] + removed[1];
  }

  private async cacheHit(entityId: string): Promise<CacheHit<T> | null> {
    if (!this.enabled) {
      this.telemetry({ kind: "miss", reason: "disabled" });
      return null;
    }
    try {
      await this.initialize();
    } catch (error) {
      this.telemetry({ kind: "error", reason: errorName(error) });
      return null;
    }
    const backend = this.backend();
    if (!backend) {
      this.telemetry({ kind: "miss", reason: "policy" });
      return null;
    }
    try {
      const key = cacheEntryKey(this.scope, entityId);
      const entry = await backend.get<T>(key);
      if (!entry) {
        this.telemetry({ kind: "miss" });
        return null;
      }
      const now = this.now();
      if (!isValidEntry({
        entityId,
        metadata: entry.metadata,
        now,
        persistencePolicy: this.persistencePolicy,
        policy: this.policy,
        scope: this.scope,
      })) {
        await backend.delete(key).catch(() => false);
        this.telemetry({ kind: "miss", reason: "invalid" });
        return null;
      }
      if (entry.metadata.expiresAt <= now) {
        await backend.delete(key).catch(() => false);
        this.telemetry({ bytes: entry.metadata.sizeBytes, kind: "expired" });
        return null;
      }
      if (!this.validStoredPayload(entry.payload, entry.metadata.sizeBytes)) {
        await backend.delete(key).catch(() => false);
        this.telemetry({ kind: "miss", reason: "invalid-payload-size" });
        return null;
      }
      const sanitized = safeSanitize(this.policy.sanitize, entry.payload);
      if (sanitized === null || !this.validRenderedPayload(sanitized)) {
        await backend.delete(key).catch(() => false);
        this.telemetry({ kind: "miss", reason: "invalid-payload" });
        return null;
      }
      const freshness = entry.metadata.staleAt <= now ? "stale" : "fresh";
      await backend.touch(key, { lastAccessedAt: now }).catch(() => false);
      this.telemetry({ bytes: entry.metadata.sizeBytes, kind: freshness === "stale" ? "stale" : "hit" });
      return { ...entry, payload: sanitized, freshness };
    } catch (error) {
      this.telemetry({ kind: "error", reason: errorName(error) });
      return null;
    }
  }

  private async revalidate(
    entityId: string,
    loader: CacheLoader<T>,
    observed: CacheHit<T> | null,
    canPublish: () => boolean,
    signal?: AbortSignal,
  ): Promise<CacheRevalidationResult<T>> {
    const key = cacheEntryKey(this.scope, entityId);
    return runSingleFlight(key, async () => {
      const latest = await this.cacheHit(entityId);
      if (latest && (!observed || latest.metadata.cachedAt > observed.metadata.cachedAt)) {
        return { changed: !observed || latest.metadata.revision !== observed.metadata.revision, payload: latest.payload, revision: latest.metadata.revision };
      }
      const current = latest ?? observed;
      let response: CacheNetworkResult<T>;
      try {
        response = await loader({
          etag: current?.metadata.etag,
          knownRevision: current?.metadata.revision,
          signal,
        });
      } catch (error) {
        if (errorName(error) !== "AbortError") {
          this.telemetry({
            kind: "error",
            reason: errorName(error),
            revalidation: Boolean(current),
          });
        }
        throw error;
      }
      if (response.kind === "not_modified") {
        if (!current) {
          throw new Error("A not_modified response requires a cached value.");
        }
        await withPublicationLock(this.persistentBackend.durabilityKey(), async () => {
          if (canPublish()) await this.refreshMetadata(current.metadata, response.revision, response.etag);
        });
        this.telemetry({ kind: "not_modified" });
        return { changed: false, payload: current.payload, revision: response.revision?.trim() || current.metadata.revision };
      }
      const revision = String(response.revision || "").trim();
      const sanitized = safeSanitize(this.policy.sanitize, response.payload);
      if (sanitized !== null && revision) {
        await this.storeValue(entityId, sanitized, revision, response.etag, Boolean(current), canPublish);
      }
      return { changed: !current || current.metadata.revision !== revision, payload: sanitized ?? response.payload, revision };
    });
  }

  private async storeValue(
    entityId: string,
    payload: T,
    revision: string,
    etag: string | undefined,
    revalidation: boolean,
    canPublish: () => boolean,
  ): Promise<void> {
    const backend = this.backend();
    if (!backend) {
      return;
    }
    try {
      const sizeBytes = validatedPayloadSize(payload);
      if (sizeBytes > this.policy.maxEntryBytes || !(await this.quotaAdapter.canWrite(sizeBytes))) {
        this.telemetry({ bytes: sizeBytes, kind: "error", reason: "budget-or-quota" });
        return;
      }
      await withPublicationLock(this.persistentBackend.durabilityKey(), async () => {
        // Quota, cleanup, cancellation and lease expiry can all race the loader.
        if (!canPublish() || this.backend() !== backend) return;
        const now = this.now();
        const lease = this.getAccessLease();
        const metadata = createEntryMetadata({
          accessLease: lease,
          entityId,
          etag,
          now,
          persistencePolicy: this.persistencePolicy,
          policy: this.policy,
          revision,
          scope: this.scope,
          sizeBytes,
        });
        await backend.put({ metadata, payload });
        this.telemetry({ bytes: sizeBytes, kind: "write", revalidation });
        await enforceCacheBudgets(backend, this.scope, this.budgets, now, this.telemetry);
      });
    } catch (error) {
      this.telemetry({ kind: "error", reason: errorName(error) });
    }
  }

  private async refreshMetadata(metadata: CacheEntryMetadata, revision?: string, etag?: string): Promise<void> {
    const backend = this.backend();
    if (!backend) {
      return;
    }
    const now = this.now();
    await backend.touch(metadata.key, {
      ...(this.policy.dataClass === "public" || this.persistencePolicy !== "cache"
        ? {}
        : { accessLeaseExpiresAt: this.getAccessLease()?.expiresAt }),
      cachedAt: now,
      ...(etag ? { etag } : {}),
      expiresAt: now + this.policy.expiryTtlMs,
      lastAccessedAt: now,
      revision: revision?.trim() || metadata.revision,
      staleAt: now + this.policy.freshTtlMs,
    }).catch((error) => {
      this.telemetry({ kind: "error", reason: errorName(error) });
      return false;
    });
  }

  private backend(): CacheBackend | null {
    if (!this.enabled || this.persistencePolicy === "deny") {
      return null;
    }
    if (this.persistencePolicy === "session") {
      return this.memoryBackend;
    }
    return hasValidAccessLease(this.policy.dataClass, this.getAccessLease(), this.now())
      ? this.persistentBackend
      : null;
  }

  private initialize(): Promise<void> {
    if (!this.initialized) {
      this.initialized = initializeResourceBackends({
        memoryBackend: this.memoryBackend,
        persistencePolicy: this.persistencePolicy,
        persistentBackend: this.persistentBackend,
        scope: this.scope,
        telemetry: this.telemetry,
      });
    }
    return this.initialized;
  }

  private revalidationMode(): "always" | "stale" | "never" {
    return this.policy.revalidateOnRead ?? "stale";
  }

  private validStoredPayload(payload: unknown, recordedSize: number): boolean {
    try {
      const actualSize = validatedPayloadSize(payload);
      return actualSize === recordedSize && actualSize <= this.policy.maxEntryBytes;
    } catch {
      return false;
    }
  }

  private validRenderedPayload(payload: T): boolean {
    try {
      return validatedPayloadSize(payload) <= this.policy.maxEntryBytes;
    } catch {
      return false;
    }
  }
}

function errorName(error: unknown): string {
  return error instanceof Error ? error.name : "unknown";
}
