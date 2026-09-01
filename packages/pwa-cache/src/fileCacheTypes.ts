import type {
  AccessLease,
  CacheCleanupResult,
  CachePrincipal,
  MaverickDataClass,
  MaverickProvenance,
  StorageQuotaAdapter,
} from "./types";

export const PWA_FILE_CACHE_SCHEMA_VERSION = 2;
export const PWA_FILE_CACHE_POLICY_REVISION = "maverick.local-persistence-policy.v2";
export const DEFAULT_PWA_FILE_CACHE_MAX_ENTRY_BYTES = 64 * 1024 * 1024;
export const DEFAULT_PWA_FILE_CACHE_SCOPE_BUDGET_BYTES = 128 * 1024 * 1024;
export const DEFAULT_PWA_FILE_CACHE_GLOBAL_BUDGET_BYTES = 256 * 1024 * 1024;

export type FileCacheState = "writing" | "ready" | "invalid" | "error";

export type FileCacheDescriptor = {
  cacheApproved?: boolean;
  contentType: string;
  dataClass: MaverickDataClass;
  expectedSha256?: string;
  fileId: string;
  privacyApproved?: boolean;
  provenance: MaverickProvenance;
  regulatedAllowlisted?: boolean;
  sizeBytes: number;
  sourceVersion: string;
};

export type FileCacheRecord = CachePrincipal & {
  accessLeaseExpiresAt?: number;
  cachedAt: number;
  cleanupEpoch: number;
  contentType: string;
  dataClass: MaverickDataClass;
  etag: string;
  fileId: string;
  key: string;
  lastAccessedAt: number;
  lastVerifiedAt: number;
  opfsPath: string;
  policyRevision: typeof PWA_FILE_CACHE_POLICY_REVISION;
  provenance: MaverickProvenance;
  schemaVersion: typeof PWA_FILE_CACHE_SCHEMA_VERSION;
  sha256: string;
  sizeBytes: number;
  sourceVersion: string;
  state: FileCacheState;
  writtenBytes: number;
  writeGeneration: number;
  writeLeaseExpiresAt?: number;
  writerSessionId?: string;
};

export type FileCacheFilter = Partial<Pick<FileCacheRecord,
  "userId" | "workspaceId" | "appId" | "fileId" | "sourceVersion" | "state"
>>;

export type FileCacheCleanupMarker = {
  cleanupEpoch: number;
  createdAt: number;
  filter: FileCacheFilter;
  id: string;
  kind: "file-cache-cleanup";
};

export type FileCachePublishResult = {
  obsoleteRecords: FileCacheRecord[];
  published: boolean;
};

export interface FileCacheManifestStore {
  createCleanupMarker(filter: FileCacheFilter): Promise<FileCacheCleanupMarker>;
  delete(key: string): Promise<boolean>;
  deleteCleanupMarker(id: string): Promise<void>;
  deleteWriting(record: FileCacheRecord): Promise<boolean>;
  get(key: string): Promise<FileCacheRecord | null>;
  getCleanupEpoch(): Promise<number>;
  initialize(): Promise<void>;
  list(filter?: FileCacheFilter): Promise<FileCacheRecord[]>;
  listCleanupMarkers(): Promise<FileCacheCleanupMarker[]>;
  publishReady(record: FileCacheRecord): Promise<FileCachePublishResult>;
  put(record: FileCacheRecord): Promise<void>;
  reserveWriting(record: FileCacheRecord, expectedCleanupEpoch: number): Promise<FileCacheRecord | null>;
  updateReady(record: FileCacheRecord): Promise<boolean>;
  updateWriting(record: FileCacheRecord): Promise<boolean>;
}

export interface FileCacheByteWriter {
  close(): Promise<void>;
  truncate(size: number): Promise<void>;
  write(chunk: Uint8Array): Promise<void>;
}

export interface FileCacheByteStore {
  available(): boolean;
  createWriter(path: string, offset: number): Promise<FileCacheByteWriter>;
  delete(path: string): Promise<void>;
  initialize(): Promise<void>;
  list(): Promise<string[]>;
  read(path: string): Promise<Blob | null>;
}

export type FileCacheTelemetryEvent = {
  bytes?: number;
  count?: number;
  kind: "hit" | "miss" | "write" | "ready" | "error" | "evict";
  reason?: string;
};

export type FileCacheOpenRequest = {
  descriptor: FileCacheDescriptor;
  signal?: AbortSignal;
  url: string;
};

export type FileCacheOpenResult = {
  blob: Blob;
  cacheCompletion?: Promise<void>;
  etag: string;
  source: "cache" | "network";
};

export type PwaFileCacheOptions = {
  accessLease?: AccessLease;
  byteStore?: FileCacheByteStore;
  enabled?: boolean;
  fetchImpl?: typeof fetch;
  globalBudgetBytes?: number;
  manifestStore?: FileCacheManifestStore;
  maxEntryBytes?: number;
  maxScopeBytes?: number;
  now?: () => number;
  quotaAdapter?: StorageQuotaAdapter;
  telemetry?: (event: FileCacheTelemetryEvent) => void;
};

export type FileCacheDiagnostics = {
  available: boolean;
  bytes: number;
  entryCount: number;
  pendingCleanupCount: number;
};

export interface FileCacheMaintenance {
  clear(filter?: FileCacheFilter): Promise<CacheCleanupResult>;
  diagnostics(): Promise<FileCacheDiagnostics>;
  initialize(): Promise<void>;
  renewAccessLease(principal: CachePrincipal, lease: AccessLease): Promise<void>;
}
