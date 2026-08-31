import { cacheEntryKey } from "./scope";
import {
  PWA_CACHE_ENTRY_SCHEMA_VERSION,
  type AccessLease,
  type CacheEntryMetadata,
  type CacheReadResult,
  type CacheScope,
  type LocalPersistencePolicy,
  type ResourceCachePolicy,
  type StoredCacheEntry,
} from "./types";

export type CacheHit<T> = StoredCacheEntry<T> & { freshness: "fresh" | "stale" };

export function createEntryMetadata<T>(options: {
  accessLease?: AccessLease;
  entityId: string;
  etag?: string;
  now: number;
  persistencePolicy: LocalPersistencePolicy;
  policy: ResourceCachePolicy<T>;
  revision: string;
  scope: CacheScope;
  sizeBytes: number;
}): CacheEntryMetadata {
  const { accessLease, entityId, etag, now, persistencePolicy, policy, revision, scope, sizeBytes } = options;
  return {
    ...scope,
    ...(policy.dataClass === "public" || persistencePolicy !== "cache"
      ? {}
      : { accessLeaseExpiresAt: accessLease?.expiresAt }),
    cachedAt: now,
    dataClass: policy.dataClass,
    entityId,
    ...(etag ? { etag } : {}),
    expiresAt: now + policy.expiryTtlMs,
    key: cacheEntryKey(scope, entityId),
    lastAccessedAt: now,
    policy: "cache",
    provenance: policy.provenance,
    revision,
    schemaVersion: PWA_CACHE_ENTRY_SCHEMA_VERSION,
    sizeBytes,
    staleAt: now + policy.freshTtlMs,
  };
}

export function isValidEntry<T>(options: {
  entityId: string;
  metadata: CacheEntryMetadata;
  now: number;
  persistencePolicy: LocalPersistencePolicy;
  policy: ResourceCachePolicy<T>;
  scope: CacheScope;
}): boolean {
  const { entityId, metadata, now, persistencePolicy, policy, scope } = options;
  return metadata.schemaVersion === PWA_CACHE_ENTRY_SCHEMA_VERSION
    && metadata.policy === "cache"
    && metadata.userId === scope.userId
    && metadata.workspaceId === scope.workspaceId
    && metadata.appId === scope.appId
    && metadata.resource === scope.resource
    && metadata.entityId === entityId
    && metadata.policyRevision === scope.policyRevision
    && metadata.dataClass === policy.dataClass
    && metadata.provenance === policy.provenance
    && metadata.revision.trim().length > 0
    && (policy.dataClass === "public"
      || persistencePolicy === "session"
      || (metadata.accessLeaseExpiresAt ?? 0) > now);
}

export function resultFromCacheHit<T>(hit: CacheHit<T>): CacheReadResult<T> {
  return {
    freshness: hit.freshness,
    payload: hit.payload,
    revision: hit.metadata.revision,
    source: "cache",
  };
}

export function safeSanitize<T>(sanitizer: (payload: unknown) => T | null, payload: unknown): T | null {
  try {
    return sanitizer(payload);
  } catch {
    return null;
  }
}
