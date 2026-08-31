import { deriveLocalPersistencePolicy, hasValidAccessLease } from "./policy";
import { validatePrincipal } from "./scope";
import {
  PWA_FILE_CACHE_POLICY_REVISION,
  PWA_FILE_CACHE_SCHEMA_VERSION,
  type FileCacheDescriptor,
  type FileCacheRecord,
} from "./fileCacheTypes";
import type { AccessLease, CachePrincipal } from "./types";

const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const STRONG_ETAG_PATTERN = /^"[^"\u0000-\u001f\u007f]+"$/u;
const MAX_IDENTITY_LENGTH = 256;
const MAX_CONTENT_TYPE_LENGTH = 255;

export function validateFileCacheDescriptor(descriptor: FileCacheDescriptor): FileCacheDescriptor {
  const fileId = boundedIdentity("fileId", descriptor.fileId);
  const sourceVersion = boundedIdentity("sourceVersion", descriptor.sourceVersion);
  const contentType = String(descriptor.contentType || "").trim().toLowerCase();
  if (!contentType || contentType.length > MAX_CONTENT_TYPE_LENGTH || /[\r\n]/u.test(contentType)) {
    throw new TypeError("PWA file-cache contentType is invalid.");
  }
  if (!Number.isSafeInteger(descriptor.sizeBytes) || descriptor.sizeBytes < 0) {
    throw new TypeError("PWA file-cache sizeBytes must be a non-negative integer.");
  }
  const expectedSha256 = descriptor.expectedSha256?.trim().toLowerCase();
  if (expectedSha256 !== undefined && !SHA256_PATTERN.test(expectedSha256)) {
    throw new TypeError("PWA file-cache expectedSha256 must be a lowercase SHA-256 digest.");
  }
  return {
    ...descriptor,
    contentType,
    ...(expectedSha256 ? { expectedSha256 } : {}),
    fileId,
    sourceVersion,
  };
}

export function fileCacheKey(principal: CachePrincipal, descriptor: FileCacheDescriptor): string {
  const scope = validatePrincipal(principal);
  const file = validateFileCacheDescriptor(descriptor);
  return JSON.stringify([
    scope.userId,
    scope.workspaceId,
    scope.appId,
    file.fileId,
    file.sourceVersion,
    PWA_FILE_CACHE_POLICY_REVISION,
    PWA_FILE_CACHE_SCHEMA_VERSION,
  ]);
}

export function fileCacheDescriptorIsEligible(
  descriptor: FileCacheDescriptor,
  accessLease: AccessLease | undefined,
  now: number,
  appId = "storage",
): boolean {
  const policy = deriveLocalPersistencePolicy(appId, "file-bytes", {
    cacheApproved: descriptor.cacheApproved,
    dataClass: descriptor.dataClass,
    expiryTtlMs: 24 * 60 * 60_000,
    freshTtlMs: 0,
    maxEntryBytes: Math.max(1, descriptor.sizeBytes),
    maxScopeBytes: Math.max(1, descriptor.sizeBytes),
    policyRevision: PWA_FILE_CACHE_POLICY_REVISION,
    privacyApproved: descriptor.privacyApproved,
    provenance: descriptor.provenance,
    regulatedAllowlisted: descriptor.regulatedAllowlisted,
    sanitize: () => null,
    schemaRevision: "storage.file-bytes.v1",
  });
  return policy === "cache" && hasValidAccessLease(descriptor.dataClass, accessLease, now);
}

export function recordMatchesDescriptor(
  record: FileCacheRecord,
  principal: CachePrincipal,
  descriptor: FileCacheDescriptor,
  accessLease: AccessLease | undefined,
  now: number,
): boolean {
  const scope = validatePrincipal(principal);
  return record.schemaVersion === PWA_FILE_CACHE_SCHEMA_VERSION
    && record.policyRevision === PWA_FILE_CACHE_POLICY_REVISION
    && record.state === "ready"
    && record.key === fileCacheKey(scope, descriptor)
    && record.userId === scope.userId
    && record.workspaceId === scope.workspaceId
    && record.appId === scope.appId
    && record.fileId === descriptor.fileId
    && record.sourceVersion === descriptor.sourceVersion
    && record.contentType === descriptor.contentType
    && record.dataClass === descriptor.dataClass
    && record.provenance === descriptor.provenance
    && record.sizeBytes === descriptor.sizeBytes
    && record.writtenBytes === descriptor.sizeBytes
    && isStrongEtag(record.etag)
    && SHA256_PATTERN.test(record.sha256)
    && (!descriptor.expectedSha256 || descriptor.expectedSha256 === record.sha256)
    && (descriptor.dataClass === "public"
      || (hasValidAccessLease(descriptor.dataClass, accessLease, now)
        && typeof record.accessLeaseExpiresAt === "number"
        && record.accessLeaseExpiresAt >= now));
}

export function isStrongEtag(value: string): boolean {
  return STRONG_ETAG_PATTERN.test(value.trim()) && !value.trim().startsWith("W/");
}

function boundedIdentity(name: string, value: string): string {
  const normalized = String(value || "").trim();
  if (!normalized || normalized.length > MAX_IDENTITY_LENGTH || /[\u0000-\u001f\u007f]/u.test(normalized)) {
    throw new TypeError(`PWA file-cache ${name} is invalid.`);
  }
  return normalized;
}
