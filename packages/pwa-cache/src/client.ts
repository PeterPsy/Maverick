import { CacheBus, type CacheBusMessage } from "./cacheBus";
import { MemoryCacheBackend } from "./memoryBackend";
import { BrowserStorageQuotaAdapter } from "./quota";
import { ResilientCacheBackend } from "./resilientBackend";
import { PwaCacheResource } from "./resource";
import { validatePrincipal } from "./scope";
import type {
  AccessLease,
  CacheBackend,
  PwaCacheClientOptions,
  ResourceCachePolicy,
} from "./types";

export const DEFAULT_PWA_CACHE_GLOBAL_BUDGET_BYTES = 64 * 1024 * 1024;
export const DEFAULT_PWA_CACHE_APP_BUDGET_BYTES = 32 * 1024 * 1024;

type InvalidatableResource = { invalidate(entityId?: string): Promise<number> };

export class PwaCacheClient {
  readonly appId: string;
  readonly userId: string;
  readonly workspaceId: string;
  private accessLease?: AccessLease;
  private readonly backend: CacheBackend;
  private readonly bus: CacheBus;
  private readonly enabled: boolean;
  private readonly globalBudgetBytes: number;
  private readonly maxAppBytes: number;
  private readonly memoryBackend = new MemoryCacheBackend();
  private readonly now: () => number;
  private readonly options: PwaCacheClientOptions;
  private readonly resources = new Map<string, InvalidatableResource>();
  private readonly unsubscribeBus: () => void;

  constructor(options: PwaCacheClientOptions, bus = new CacheBus()) {
    const principal = validatePrincipal(options);
    this.userId = principal.userId;
    this.workspaceId = principal.workspaceId;
    this.appId = principal.appId;
    this.options = options;
    this.enabled = options.enabled === true;
    this.accessLease = options.accessLease;
    this.now = options.now ?? Date.now;
    this.globalBudgetBytes = positiveBudget(options.globalBudgetBytes, DEFAULT_PWA_CACHE_GLOBAL_BUDGET_BYTES);
    this.maxAppBytes = positiveBudget(options.maxAppBytes, DEFAULT_PWA_CACHE_APP_BUDGET_BYTES);
    this.backend = options.backend instanceof ResilientCacheBackend
      ? options.backend
      : new ResilientCacheBackend(options.backend, {
          onFailure: () => options.telemetry?.({ kind: "error", reason: "indexeddb-fallback" }),
        });
    this.bus = bus;
    this.unsubscribeBus = bus.subscribe((message) => this.handleBusMessage(message));
  }

  resource<T>(resource: string, policy: ResourceCachePolicy<T>): PwaCacheResource<T> {
    const existing = this.resources.get(resource);
    if (existing) {
      throw new Error(`PWA cache resource ${resource} is already registered for this client.`);
    }
    const scoped = new PwaCacheResource<T>({
      budgets: {
        globalBytes: this.globalBudgetBytes,
        maxAppBytes: this.maxAppBytes,
        maxScopeBytes: policy.maxScopeBytes,
      },
      enabled: this.enabled,
      getAccessLease: () => this.accessLease,
      memoryBackend: this.memoryBackend,
      now: this.now,
      persistentBackend: this.backend,
      policy,
      quotaAdapter: this.options.quotaAdapter ?? new BrowserStorageQuotaAdapter(),
      scope: {
        userId: this.userId,
        workspaceId: this.workspaceId,
        appId: this.appId,
        resource,
        policyRevision: policy.policyRevision,
      },
      telemetry: this.options.telemetry ?? (() => undefined),
    });
    this.resources.set(scoped.scope.resource, scoped);
    return scoped;
  }

  updateAccessLease(lease: AccessLease | undefined): void {
    this.accessLease = lease;
  }

  attachDataChangeListener(target: Window = window): () => void {
    const listener = (event: MessageEvent<unknown>) => {
      if (event.origin !== target.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as { entity_id?: unknown; owner_app_id?: unknown; resource?: unknown; type?: unknown };
      if (payload.type !== "maverick.app.data-changed"
          || payload.owner_app_id !== this.appId
          || typeof payload.resource !== "string") {
        return;
      }
      void this.handleDataChanged(payload.resource, typeof payload.entity_id === "string" ? payload.entity_id : undefined);
    };
    target.addEventListener("message", listener);
    return () => target.removeEventListener("message", listener);
  }

  async clear(): Promise<number> {
    const filter = { userId: this.userId, workspaceId: this.workspaceId, appId: this.appId };
    const [persistent, session] = await Promise.all([
      this.backend.clear(filter, { durable: true }).catch(() => 0),
      this.memoryBackend.clear(filter),
    ]);
    this.bus.publish({ appId: this.appId, type: "scope-cleared", userId: this.userId, workspaceId: this.workspaceId });
    return persistent + session;
  }

  dispose(): void {
    this.unsubscribeBus();
    this.bus.close();
  }

  private async handleDataChanged(resource: string, entityId?: string): Promise<void> {
    const scoped = this.resources.get(resource);
    if (!scoped) {
      return;
    }
    await scoped.invalidate(entityId);
    this.bus.publish({
      appId: this.appId,
      ...(entityId ? { entityId } : {}),
      resource,
      type: "data-changed",
      userId: this.userId,
      workspaceId: this.workspaceId,
    });
  }

  private handleBusMessage(message: CacheBusMessage): void {
    if (message.type === "all-cleared") {
      void this.memoryBackend.clear();
      return;
    }
    if (message.type === "data-changed") {
      if (message.userId === this.userId && message.workspaceId === this.workspaceId && message.appId === this.appId) {
        void this.resources.get(message.resource)?.invalidate(message.entityId);
      }
      return;
    }
    if (message.type === "scope-cleared"
        && message.userId === this.userId
        && (!message.workspaceId || message.workspaceId === this.workspaceId)
        && (!message.appId || message.appId === this.appId)) {
      void this.memoryBackend.clear({ userId: this.userId, workspaceId: this.workspaceId, appId: this.appId });
    }
  }
}

export function createPwaCacheClient(options: PwaCacheClientOptions): PwaCacheClient {
  return new PwaCacheClient(options);
}

function positiveBudget(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}
