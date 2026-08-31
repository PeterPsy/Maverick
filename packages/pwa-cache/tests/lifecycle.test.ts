import { describe, expect, it, vi } from "vitest";
import {
  CacheLifecycleController,
  DurableCacheCleanupError,
  LOCAL_PERSISTENCE_POLICY_REVISION,
  PWA_CACHE_ENTRY_SCHEMA_VERSION,
  RetryCoordinator,
  type CacheEntryMetadata,
} from "../src";
import { CacheBus, MemoryCacheBackend, ResilientCacheBackend, cacheEntryKey } from "../src/testing";

function entry(overrides: Partial<CacheEntryMetadata> = {}): CacheEntryMetadata {
  const scope = {
    appId: overrides.appId ?? "docs",
    policyRevision: overrides.policyRevision ?? LOCAL_PERSISTENCE_POLICY_REVISION,
    resource: overrides.resource ?? "records",
    schemaRevision: overrides.schemaRevision ?? "records.v1",
    userId: overrides.userId ?? "user-a",
    workspaceId: overrides.workspaceId ?? "default",
  };
  return {
    accessLeaseExpiresAt: 2_000,
    cachedAt: 1_000,
    dataClass: "workspace_internal",
    entityId: "one",
    expiresAt: 20_000,
    key: cacheEntryKey(scope, "one"),
    lastAccessedAt: 1_000,
    policy: "cache",
    provenance: "app_reference",
    revision: "r1",
    schemaVersion: PWA_CACHE_ENTRY_SCHEMA_VERSION,
    sizeBytes: 12,
    staleAt: 2_000,
    ...scope,
    ...overrides,
    schemaRevision: overrides.schemaRevision ?? scope.schemaRevision,
  };
}

describe("cache lifecycle", () => {
  it("renews private leases after fresh authentication and clears the previous workspace", async () => {
    const backend = new MemoryCacheBackend();
    await backend.put({ metadata: entry(), payload: { value: "one" } });
    const retry = new RetryCoordinator();
    const controller = new CacheLifecycleController({ backend, bus: new CacheBus(null), now: () => 1_500, retryCoordinator: retry });
    await controller.transition({
      accessLease: { issuedAt: 1_500, expiresAt: 5_000 },
      appId: "base-shell",
      userId: "user-a",
      workspaceId: "default",
    });
    expect((await backend.get(entry().key))?.metadata.accessLeaseExpiresAt).toBe(5_000);

    await controller.transition({ appId: "base-shell", userId: "user-a", workspaceId: "other" });
    expect(await backend.list({ workspaceId: "default" })).toEqual([]);
  });

  it("clears every user scope and pending retry on logout", async () => {
    vi.useFakeTimers();
    const backend = new MemoryCacheBackend();
    await backend.put({ metadata: entry(), payload: { value: "one" } });
    await backend.put({ metadata: entry({ workspaceId: "other" }), payload: { value: "two" } });
    const retry = new RetryCoordinator();
    const controller = new CacheLifecycleController({ backend, bus: new CacheBus(null), retryCoordinator: retry });
    await controller.transition({ appId: "base-shell", userId: "user-a", workspaceId: "default" });
    const pending = retry.run({ key: "read:pending", operation: async () => { throw Object.assign(new Error(), { name: "MaverickTransportError" }); } });
    void pending.catch(() => undefined);
    await controller.endSession();
    expect(await backend.list({ userId: "user-a" })).toEqual([]);
    expect(retry.pendingCount()).toBe(0);
    vi.useRealTimers();
  });

  it("clears unknown persisted scopes after a cold authorization failure", async () => {
    const backend = new MemoryCacheBackend();
    await backend.put({ metadata: entry(), payload: { value: "one" } });
    await backend.put({ metadata: entry({ userId: "user-b" }), payload: { value: "two" } });
    const controller = new CacheLifecycleController({ backend, bus: new CacheBus(null) });

    await controller.authorizationFailure();

    expect(await backend.list()).toEqual([]);
  });

  it("invalidates only the owning app resource after a data-changed event", async () => {
    const backend = new MemoryCacheBackend();
    await backend.put({ metadata: entry(), payload: { value: "one" } });
    await backend.put({ metadata: entry({ appId: "mail", resource: "threads" }), payload: { value: "mail" } });
    const controller = new CacheLifecycleController({ backend, bus: new CacheBus(null) });
    await controller.transition({ appId: "base-shell", userId: "user-a", workspaceId: "default" });
    expect(await controller.handleDataChanged({ ownerAppId: "docs", resource: "records" })).toMatchObject({
      removed: 1,
      status: "complete",
    });
    expect((await backend.list()).map((item) => item.appId)).toEqual(["mail"]);
  });

  it("reports redaction-safe aggregate diagnostics and clears all data entries", async () => {
    const backend = new MemoryCacheBackend();
    await backend.put({ metadata: entry(), payload: { value: "one" } });
    const controller = new CacheLifecycleController({
      backend,
      bus: new CacheBus(null),
      quotaAdapter: {
        canWrite: async () => true,
        estimate: async () => ({ quota: 1_000, supported: true, usage: 200 }),
      },
    });
    expect(await controller.diagnostics()).toEqual({
      backend: "memory",
      cacheBytes: 12,
      entryCount: 1,
      originQuotaBytes: 1_000,
      originUsageBytes: 200,
      pendingCleanupCount: 0,
    });
    expect(await controller.clearAll()).toMatchObject({ removed: 1, status: "complete" });
    expect(await backend.list()).toEqual([]);
  });

  it("falls back to RAM after injected IndexedDB-style failures", async () => {
    class FailingBackend extends MemoryCacheBackend {
      override async initialize(): Promise<void> { throw new Error("injected storage failure"); }
    }
    const resilient = new ResilientCacheBackend(new FailingBackend());
    await resilient.initialize();
    expect(resilient.mode()).toBe("memory");
    await resilient.put({ metadata: entry(), payload: { value: "safe fallback" } });
    expect((await resilient.get(entry().key))?.payload).toEqual({ value: "safe fallback" });
  });

  it("reports durable cleanup as pending and blocks cache reuse when persistent deletion fails", async () => {
    class FailingClearBackend extends MemoryCacheBackend {
      failClear = true;

      override async clear(...args: Parameters<MemoryCacheBackend["clear"]>): Promise<number> {
        if (this.failClear && args[1]?.durable) {
          throw new Error("injected durable cleanup failure");
        }
        return super.clear(...args);
      }
    }

    const primary = new FailingClearBackend();
    await primary.put({ metadata: entry(), payload: { value: "must-not-reappear" } });
    const resilient = new ResilientCacheBackend(primary);
    const controller = new CacheLifecycleController({ backend: resilient, bus: new CacheBus(null) });

    await expect(resilient.clear({ userId: "user-a" }, { durable: true })).rejects.toBeInstanceOf(DurableCacheCleanupError);
    expect(resilient.mode()).toBe("memory");
    expect(await primary.list()).toHaveLength(1);
    expect(await resilient.get(entry().key)).toBeNull();
    expect(await resilient.pendingCleanupCount()).toBeGreaterThan(0);

    const pending = await controller.clearAll();
    expect(pending).toMatchObject({ status: "pending" });

    primary.failClear = false;
    const completed = await controller.clearAll();
    expect(completed).toMatchObject({ status: "complete" });
    expect(await primary.list()).toEqual([]);
    expect(await resilient.pendingCleanupCount()).toBe(0);
  });
});
