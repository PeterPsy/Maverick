import { cacheEntryKey } from "./scope";
import { PRIVATE_ACCESS_LEASE_MAX_MS } from "./policy";
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
    && metadata.schemaRevision === scope.schemaRevision
    && metadata.dataClass === policy.dataClass
    && metadata.provenance === policy.provenance
    && metadata.key === cacheEntryKey(scope, entityId)
    && typeof metadata.revision === "string"
    && metadata.revision.trim().length > 0
    && validEntryBounds(metadata, policy, now)
    && (policy.dataClass === "public"
      || persistencePolicy === "session"
      || validPrivateAccessLease(metadata, now));
}

function validEntryBounds<T>(metadata: CacheEntryMetadata, policy: ResourceCachePolicy<T>, now: number): boolean {
  return Number.isSafeInteger(metadata.cachedAt)
    && metadata.cachedAt >= 0
    && metadata.cachedAt <= now
    && Number.isSafeInteger(metadata.lastAccessedAt)
    && metadata.lastAccessedAt >= metadata.cachedAt
    && metadata.lastAccessedAt <= now
    && Number.isSafeInteger(metadata.staleAt)
    && metadata.staleAt === metadata.cachedAt + policy.freshTtlMs
    && Number.isSafeInteger(metadata.expiresAt)
    && metadata.expiresAt === metadata.cachedAt + policy.expiryTtlMs
    && Number.isSafeInteger(metadata.sizeBytes)
    && metadata.sizeBytes > 0
    && metadata.sizeBytes <= policy.maxEntryBytes;
}

function validPrivateAccessLease(metadata: CacheEntryMetadata, now: number): boolean {
  return Number.isSafeInteger(metadata.accessLeaseExpiresAt)
    && (metadata.accessLeaseExpiresAt ?? 0) > now
    && (metadata.accessLeaseExpiresAt ?? 0) <= metadata.cachedAt + PRIVATE_ACCESS_LEASE_MAX_MS;
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
