import { CacheBus } from "./cacheBus";
import { BrowserStorageQuotaAdapter } from "./quota";
import { ResilientCacheBackend } from "./resilientBackend";
import { validatePrincipal } from "./scope";
import { PRIVATE_ACCESS_LEASE_MAX_MS } from "./policy";
import type {
  AccessLease,
  CacheBackend,
  CacheDiagnostics,
  CacheEntryMetadata,
  CachePrincipal,
  StorageQuotaAdapter,
} from "./types";
import type { RetryCoordinator } from "./retry";

export type CacheLifecyclePrincipal = CachePrincipal & { accessLease?: AccessLease };

export type CacheLifecycleControllerOptions = {
  backend?: CacheBackend;
  bus?: CacheBus;
  now?: () => number;
  quotaAdapter?: StorageQuotaAdapter;
  retryCoordinator?: RetryCoordinator;
};

export class CacheLifecycleController {
  private readonly backend: CacheBackend;
  private readonly bus: CacheBus;
  private readonly now: () => number;
  private readonly quotaAdapter: StorageQuotaAdapter;
  private readonly retryCoordinator?: RetryCoordinator;
  private current: CacheLifecyclePrincipal | null = null;

  constructor(options: CacheLifecycleControllerOptions = {}) {
    this.backend = options.backend instanceof ResilientCacheBackend
      ? options.backend
      : new ResilientCacheBackend(options.backend);
    this.bus = options.bus ?? new CacheBus();
    this.now = options.now ?? Date.now;
    this.quotaAdapter = options.quotaAdapter ?? new BrowserStorageQuotaAdapter();
    this.retryCoordinator = options.retryCoordinator;
  }

  async initialize(): Promise<void> {
    await this.backend.initialize();
  }

  async transition(next: CacheLifecyclePrincipal): Promise<void> {
    const principal = { ...validatePrincipal(next), accessLease: normalizeLease(next.accessLease, this.now()) };
    const previous = this.current;
    if (previous && !samePrincipal(previous, principal)) {
      await this.clearPrevious(previous, principal);
    }
    this.current = principal;
    this.retryCoordinator?.setScope(scopeKey(principal));
    if (principal.accessLease) {
      await this.renewAccessLease(principal).catch(() => undefined);
    }
  }

  async endSession(): Promise<void> {
    const previous = this.current;
    this.current = null;
    this.retryCoordinator?.setScope("anonymous");
    if (!previous) {
      await this.clearAll().catch(() => 0);
      return;
    }
    await this.clearFilter({ userId: previous.userId });
  }

  async authorizationFailure(principal = this.current): Promise<void> {
    this.retryCoordinator?.setScope("anonymous");
    if (!principal) {
      await this.clearAll().catch(() => 0);
      return;
    }
    await this.clearFilter({ userId: principal.userId, workspaceId: principal.workspaceId });
    if (this.current && samePrincipal(this.current, principal)) {
      this.current = null;
    }
  }

  async handleDataChanged(payload: {
    entityId?: string;
    ownerAppId: string;
    resource: string;
  }): Promise<number> {
    if (!this.current) {
      return 0;
    }
    const filter = {
      userId: this.current.userId,
      workspaceId: this.current.workspaceId,
      appId: payload.ownerAppId,
      resource: payload.resource,
      ...(payload.entityId ? { entityId: payload.entityId } : {}),
    };
    const removed = await this.backend.clear(filter, { durable: true }).catch(() => 0);
    this.bus.publish({
      appId: payload.ownerAppId,
      ...(payload.entityId ? { entityId: payload.entityId } : {}),
      resource: payload.resource,
      type: "data-changed",
      userId: this.current.userId,
      workspaceId: this.current.workspaceId,
    });
    return removed;
  }

  async clearAll(): Promise<number> {
    const removed = await this.backend.clear({}, { durable: true });
    this.bus.publish({ type: "all-cleared" });
    return removed;
  }

  dispose(): void {
    this.bus.close();
  }

  async diagnostics(): Promise<CacheDiagnostics> {
    await this.backend.initialize();
    const [entries, pendingCleanupCount, storage] = await Promise.all([
      this.backend.list(),
      this.backend.pendingCleanupCount(),
      this.quotaAdapter.estimate(),
    ]);
    return {
      backend: this.backend.mode(),
      cacheBytes: entries.reduce((total, entry) => total + entry.sizeBytes, 0),
      entryCount: entries.length,
      originQuotaBytes: storage.quota,
      originUsageBytes: storage.usage,
      pendingCleanupCount,
    };
  }

  private async clearPrevious(previous: CacheLifecyclePrincipal, next: CacheLifecyclePrincipal): Promise<void> {
    const filter = previous.userId !== next.userId
      ? { userId: previous.userId }
      : { userId: previous.userId, workspaceId: previous.workspaceId };
    await this.clearFilter(filter);
  }

  private async clearFilter(filter: { userId: string; workspaceId?: string }): Promise<void> {
    await this.backend.clear(filter, { durable: true }).catch(() => 0);
    this.bus.publish({ type: "scope-cleared", ...filter });
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
