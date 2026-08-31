import { CacheBus } from "./cacheBus";
import { createBrowserFileCacheMaintenance } from "./fileCacheMaintenance";
import { BrowserStorageQuotaAdapter } from "./quota";
import { ResilientCacheBackend } from "./resilientBackend";
import { validatePrincipal } from "./scope";
import { PRIVATE_ACCESS_LEASE_MAX_MS } from "./policy";
import type {
  AccessLease,
  CacheBackend,
  CacheCleanupResult,
  CacheDiagnostics,
  CacheEntryMetadata,
  CacheFilter,
  CachePrincipal,
  StorageQuotaAdapter,
} from "./types";
import type { FileCacheFilter, FileCacheMaintenance } from "./fileCacheTypes";
import type { RetryCoordinator } from "./retry";

export type CacheLifecyclePrincipal = CachePrincipal & { accessLease?: AccessLease };

export type CacheLifecycleControllerOptions = {
  backend?: CacheBackend;
  bus?: CacheBus;
  fileCacheMaintenance?: FileCacheMaintenance;
  now?: () => number;
  quotaAdapter?: StorageQuotaAdapter;
  retryCoordinator?: RetryCoordinator;
};

export class CacheLifecycleController {
  private readonly backend: CacheBackend;
  private readonly bus: CacheBus;
  private readonly fileCache: FileCacheMaintenance;
  private readonly now: () => number;
  private readonly quotaAdapter: StorageQuotaAdapter;
  private readonly retryCoordinator?: RetryCoordinator;
  private current: CacheLifecyclePrincipal | null = null;

  constructor(options: CacheLifecycleControllerOptions = {}) {
    this.backend = options.backend instanceof ResilientCacheBackend
      ? options.backend
      : new ResilientCacheBackend(options.backend);
    this.bus = options.bus ?? new CacheBus();
    this.fileCache = options.fileCacheMaintenance ?? createBrowserFileCacheMaintenance();
    this.now = options.now ?? Date.now;
    this.quotaAdapter = options.quotaAdapter ?? new BrowserStorageQuotaAdapter();
    this.retryCoordinator = options.retryCoordinator;
  }

  async initialize(): Promise<void> {
    await Promise.all([this.backend.initialize(), this.fileCache.initialize()]);
  }

  async transition(next: CacheLifecyclePrincipal): Promise<CacheCleanupResult> {
    const principal = { ...validatePrincipal(next), accessLease: normalizeLease(next.accessLease, this.now()) };
    const previous = this.current;
    let cleanup = completeCleanup();
    if (previous && !samePrincipal(previous, principal)) {
      cleanup = await this.clearPrevious(previous, principal);
    }
    this.current = principal;
    this.retryCoordinator?.setScope(scopeKey(principal));
    if (principal.accessLease) {
      await Promise.all([
        this.renewAccessLease(principal).catch(() => undefined),
        this.fileCache.renewAccessLease({
          appId: "storage",
          userId: principal.userId,
          workspaceId: principal.workspaceId,
        }, principal.accessLease).catch(() => undefined),
      ]);
    }
    return cleanup;
  }

  async endSession(): Promise<CacheCleanupResult> {
    const previous = this.current;
    this.current = null;
    this.retryCoordinator?.setScope("anonymous");
    if (!previous) {
      return this.clearAll();
    }
    return this.clearFilter({ userId: previous.userId });
  }

  async authorizationFailure(principal = this.current): Promise<CacheCleanupResult> {
    this.retryCoordinator?.setScope("anonymous");
    if (!principal) {
      return this.clearAll();
    }
    const cleanup = await this.clearFilter({ userId: principal.userId, workspaceId: principal.workspaceId });
    if (this.current && samePrincipal(this.current, principal)) {
      this.current = null;
    }
    return cleanup;
  }

  async handleDataChanged(payload: {
    entityId?: string;
    ownerAppId: string;
    resource: string;
  }): Promise<CacheCleanupResult> {
    if (!this.current) {
      return completeCleanup();
    }
    const filter = {
      userId: this.current.userId,
      workspaceId: this.current.workspaceId,
      appId: payload.ownerAppId,
      resource: payload.resource,
      ...(payload.entityId ? { entityId: payload.entityId } : {}),
    };
    const cleanup = await this.clearWithStatus(filter);
    this.bus.publish({
      appId: payload.ownerAppId,
      ...(payload.entityId ? { entityId: payload.entityId } : {}),
      resource: payload.resource,
      type: "data-changed",
      userId: this.current.userId,
      workspaceId: this.current.workspaceId,
    });
    return cleanup;
  }

  async clearAll(): Promise<CacheCleanupResult> {
    const cleanup = await this.clearWithStatus({});
    this.bus.publish({ type: "all-cleared" });
    return cleanup;
  }

  dispose(): void {
    this.bus.close();
  }

  async diagnostics(): Promise<CacheDiagnostics> {
    await this.backend.initialize();
    const [entries, pendingCleanupCount, storage, fileCache] = await Promise.all([
      this.backend.list(),
      this.backend.pendingCleanupCount(),
      this.quotaAdapter.estimate(),
      this.fileCache.diagnostics(),
    ]);
    const structuredCacheBytes = entries.reduce((total, entry) => total + entry.sizeBytes, 0);
    return {
      backend: this.backend.mode(),
      cacheBytes: structuredCacheBytes + fileCache.bytes,
      entryCount: entries.length + fileCache.entryCount,
      fileCacheAvailable: fileCache.available,
      fileCacheBytes: fileCache.bytes,
      fileCacheEntryCount: fileCache.entryCount,
      originQuotaBytes: storage.quota,
      originUsageBytes: storage.usage,
      pendingCleanupCount: pendingCleanupCount + fileCache.pendingCleanupCount,
      structuredCacheBytes,
      structuredEntryCount: entries.length,
    };
  }

  private async clearPrevious(
    previous: CacheLifecyclePrincipal,
    next: CacheLifecyclePrincipal,
  ): Promise<CacheCleanupResult> {
    const filter = previous.userId !== next.userId
      ? { userId: previous.userId }
      : { userId: previous.userId, workspaceId: previous.workspaceId };
    return this.clearFilter(filter);
  }

  private async clearFilter(filter: { userId: string; workspaceId?: string }): Promise<CacheCleanupResult> {
    const cleanup = await this.clearWithStatus(filter);
    this.bus.publish({ type: "scope-cleared", ...filter });
    return cleanup;
  }

  private async clearWithStatus(filter: CacheFilter): Promise<CacheCleanupResult> {
    let removed = 0;
    let failed = false;
    try {
      removed = await this.backend.clear(filter, { durable: true });
    } catch {
      failed = true;
    }
    const fileCleanup = await this.fileCache.clear(fileFilter(filter)).catch(() => ({
      pendingCleanupCount: 1,
      removed: 0,
      status: "pending" as const,
    }));
    const structuredPendingCount = await this.backend.pendingCleanupCount().catch(() => failed ? 1 : 0);
    const pendingCleanupCount = structuredPendingCount + fileCleanup.pendingCleanupCount;
    return {
      pendingCleanupCount: Math.max(failed ? 1 : 0, pendingCleanupCount),
      removed: removed + fileCleanup.removed,
      status: failed || fileCleanup.status === "pending" || pendingCleanupCount > 0 ? "pending" : "complete",
    };
  }

  private async renewAccessLease(principal: CacheLifecyclePrincipal): Promise<void> {
    const lease = principal.accessLease;
    if (!lease || lease.expiresAt <= this.now()) {
      return;
    }
    const entries = await this.backend.list({ userId: principal.userId, workspaceId: principal.workspaceId });
    await Promise.all(entries.filter(isPrivateEntry).map((entry) =>
      this.backend.touch(entry.key, { accessLeaseExpiresAt: lease.expiresAt }).catch(() => false),
    ));
  }
}

export function createCacheLifecycleController(options: CacheLifecycleControllerOptions = {}): CacheLifecycleController {
  return new CacheLifecycleController(options);
}

function samePrincipal(left: CachePrincipal, right: CachePrincipal): boolean {
  return left.userId === right.userId && left.workspaceId === right.workspaceId && left.appId === right.appId;
}

function scopeKey(principal: CachePrincipal): string {
  return JSON.stringify([principal.userId, principal.workspaceId, principal.appId]);
}

function isPrivateEntry(entry: CacheEntryMetadata): boolean {
  return entry.dataClass !== "public";
}

function normalizeLease(lease: AccessLease | undefined, now: number): AccessLease | undefined {
  if (!lease
      || !Number.isFinite(lease.issuedAt)
      || !Number.isFinite(lease.expiresAt)
      || lease.issuedAt > now
      || lease.expiresAt <= now
      || lease.expiresAt - lease.issuedAt > PRIVATE_ACCESS_LEASE_MAX_MS) {
    return undefined;
  }
  return lease;
}

function completeCleanup(): CacheCleanupResult {
  return { pendingCleanupCount: 0, removed: 0, status: "complete" };
}

function fileFilter(filter: CacheFilter): FileCacheFilter {
  return {
    ...(filter.userId ? { userId: filter.userId } : {}),
    ...(filter.workspaceId ? { workspaceId: filter.workspaceId } : {}),
    ...(filter.appId ? { appId: filter.appId } : {}),
    ...(filter.entityId ? { fileId: filter.entityId } : {}),
  };
}
