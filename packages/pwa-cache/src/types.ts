export const LOCAL_PERSISTENCE_POLICY_REVISION = "maverick.local-persistence-policy.v2";
export const PWA_CACHE_ENTRY_SCHEMA_VERSION = 2;

export type MaverickDataClass =
  | "public"
  | "workspace_internal_fake"
  | "workspace_internal"
  | "personal_data"
  | "regulated_or_customer_data"
  | "credential_or_secret"
  | "host_operational_metadata"
  | "unclassified";

export type MaverickProvenance =
  | "platform_instruction"
  | "runtime_context"
  | "runtime_capabilities"
  | "workspace_instruction"
  | "agent_instruction"
  | "skill_fragment"
  | "finalization_instruction"
  | "prompt"
  | "user_input"
  | "orchestration_context"
  | "governed_context"
  | "skill"
  | "attachment"
  | "app_reference"
  | "tool_schema"
  | "tool_result"
  | "provider_state";

export type LocalPersistencePolicy = "deny" | "session" | "cache";

export type CachePrincipal = {
  userId: string;
  workspaceId: string;
  appId: string;
};

export type CacheScope = CachePrincipal & {
  resource: string;
  policyRevision: string;
};

export type AccessLease = {
  issuedAt: number;
  expiresAt: number;
};

export type ResourceCachePolicy<T> = {
  allowStale?: boolean;
  cacheApproved?: boolean;
  dataClass: MaverickDataClass;
  expiryTtlMs: number;
  freshTtlMs: number;
  maxEntryBytes: number;
  maxScopeBytes: number;
  policyRevision: string;
  privacyApproved?: boolean;
  provenance: MaverickProvenance;
  regulatedAllowlisted?: boolean;
  revalidateOnRead?: "always" | "stale" | "never";
  sanitize: (payload: unknown) => T | null;
};

export type CacheEntryMetadata = CacheScope & {
  accessLeaseExpiresAt?: number;
  cachedAt: number;
  dataClass: MaverickDataClass;
  entityId: string;
  etag?: string;
  expiresAt: number;
  key: string;
  lastAccessedAt: number;
  policy: "cache";
  provenance: MaverickProvenance;
  revision: string;
  schemaVersion: number;
  sizeBytes: number;
  staleAt: number;
};

export type StoredCacheEntry<T = unknown> = {
  metadata: CacheEntryMetadata;
  payload: T;
};

export type CacheFilter = Partial<Pick<CacheEntryMetadata,
  "userId" | "workspaceId" | "appId" | "resource" | "entityId" | "policyRevision"
>> & {
  excludePolicyRevision?: string;
};

export type CleanupMarker = {
  createdAt: number;
  filter: CacheFilter;
  id: string;
  kind: "cleanup";
};

export type BackendMode = "indexeddb" | "memory";

export interface CacheBackend {
  clear(filter?: CacheFilter, options?: { durable?: boolean }): Promise<number>;
  delete(key: string): Promise<boolean>;
  get<T>(key: string): Promise<StoredCacheEntry<T> | null>;
  initialize(): Promise<void>;
  list(filter?: CacheFilter): Promise<CacheEntryMetadata[]>;
  mode(): BackendMode;
  pendingCleanupCount(): Promise<number>;
  put<T>(entry: StoredCacheEntry<T>): Promise<void>;
  touch(key: string, patch: Partial<Pick<CacheEntryMetadata,
    "accessLeaseExpiresAt" | "cachedAt" | "etag" | "expiresAt" | "lastAccessedAt" | "revision" | "staleAt"
  >>): Promise<boolean>;
}

export type CacheNetworkResult<T> =
  | { etag?: string; kind: "value"; payload: T; revision: string }
  | { etag?: string; kind: "not_modified"; revision?: string };

export type CacheLoader<T> = (context: {
  etag?: string;
  knownRevision?: string;
  signal?: AbortSignal;
}) => Promise<CacheNetworkResult<T>>;

export type CacheRevalidationResult<T> = {
  changed: boolean;
  payload: T;
  revision: string;
};

export type CacheReadResult<T> = {
  freshness: "fresh" | "stale";
  payload: T;
  revalidation?: Promise<CacheRevalidationResult<T>>;
  revision: string;
  source: "cache" | "network";
};

export type CacheTelemetryEvent = {
  bytes?: number;
  count?: number;
  kind:
    | "hit"
    | "miss"
    | "stale"
    | "expired"
    | "write"
    | "evict"
    | "error"
    | "not_modified";
  reason?: string;
};

export type CacheTelemetry = (event: CacheTelemetryEvent) => void;

export type StorageEstimate = {
  quota: number | null;
  supported: boolean;
  usage: number | null;
};

export type CacheDiagnostics = {
  backend: BackendMode;
  cacheBytes: number;
  entryCount: number;
  originQuotaBytes: number | null;
  originUsageBytes: number | null;
  pendingCleanupCount: number;
};

export type PwaCacheClientOptions = CachePrincipal & {
  accessLease?: AccessLease;
  backend?: CacheBackend;
  enabled?: boolean;
  globalBudgetBytes?: number;
  maxAppBytes?: number;
  now?: () => number;
  quotaAdapter?: StorageQuotaAdapter;
  telemetry?: CacheTelemetry;
};

export interface StorageQuotaAdapter {
  canWrite(additionalBytes: number): Promise<boolean>;
  estimate(): Promise<StorageEstimate>;
}
