import { PWA_CACHE_ENTRY_SCHEMA_VERSION } from "./types";
import type { CacheEntryMetadata, CacheFilter, CachePrincipal, CacheScope } from "./types";

const MAX_SCOPE_PART_LENGTH = 256;
const INVALID_SCOPE_CHARACTERS = /[\u0000-\u001f\u007f]/u;

export function validatePrincipal(principal: CachePrincipal): CachePrincipal {
  return {
    userId: validateScopePart("userId", principal.userId),
    workspaceId: validateScopePart("workspaceId", principal.workspaceId),
    appId: validateScopePart("appId", principal.appId),
  };
}

export function validateScope(scope: CacheScope): CacheScope {
  return {
    ...validatePrincipal(scope),
    resource: validateScopePart("resource", scope.resource),
    policyRevision: validateScopePart("policyRevision", scope.policyRevision),
    schemaRevision: validateScopePart("schemaRevision", scope.schemaRevision),
  };
}

export function validateEntityId(entityId: string): string {
  return validateScopePart("entityId", entityId);
}

export function cacheEntryKey(
  scope: CacheScope,
  entityId: string,
  schemaVersion = PWA_CACHE_ENTRY_SCHEMA_VERSION,
): string {
  const valid = validateScope(scope);
  if (!Number.isSafeInteger(schemaVersion) || schemaVersion < 1) {
    throw new TypeError("PWA cache schemaVersion must be a positive integer.");
  }
  return JSON.stringify([
    valid.userId,
    valid.workspaceId,
    valid.appId,
    valid.resource,
    validateEntityId(entityId),
    valid.policyRevision,
    valid.schemaRevision,
    schemaVersion,
  ]);
}

export function matchesFilter(metadata: CacheEntryMetadata, filter: CacheFilter = {}): boolean {
  for (const field of ["userId", "workspaceId", "appId", "resource", "entityId", "policyRevision", "schemaRevision"] as const) {
    if (filter[field] !== undefined && metadata[field] !== filter[field]) {
      return false;
    }
  }
  return (filter.excludePolicyRevision === undefined || metadata.policyRevision !== filter.excludePolicyRevision)
    && (filter.excludeSchemaRevision === undefined || metadata.schemaRevision !== filter.excludeSchemaRevision);
}

export function scopeIdentity(scope: CacheScope): string {
  const valid = validateScope(scope);
  return JSON.stringify([
    valid.userId,
    valid.workspaceId,
    valid.appId,
    valid.resource,
    valid.policyRevision,
    valid.schemaRevision,
  ]);
}

function validateScopePart(name: string, value: string): string {
  if (typeof value !== "string") {
    throw new TypeError(`PWA cache ${name} must be a string.`);
  }
  const normalized = value.trim();
  if (!normalized) {
    throw new TypeError(`PWA cache ${name} is required.`);
  }
  if (normalized.length > MAX_SCOPE_PART_LENGTH || INVALID_SCOPE_CHARACTERS.test(normalized)) {
    throw new TypeError(`PWA cache ${name} is invalid.`);
  }
  return normalized;
}
