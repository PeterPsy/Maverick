import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CacheLifecycleController,
  DurableCacheCleanupError,
  LOCAL_PERSISTENCE_POLICY_REVISION,
  PWA_CACHE_ENTRY_SCHEMA_VERSION,
  RetryCoordinator,
  createSafeRequestRetryExecutor,
  type CacheEntryMetadata,
  type FileCacheMaintenance,
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
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

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
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("link down"));
    const pending = retry.runRequest({
      executor: createSafeRequestRetryExecutor({ endpoint: "/api/test/pending" }),
      key: "read:pending",
    });
    void pending.catch(() => undefined);
    await controller.endSession();
    expect(await backend.list({ userId: "user-a" })).toEqual([]);
    expect(retry.pendingCount()).toBe(0);
    vi.useRealTimers();
  });

  it("cancels RAM retries when Settings clears the cache", async () => {
    vi.useFakeTimers();
    const retry = new RetryCoordinator();
    const controller = new CacheLifecycleController({
      backend: new MemoryCacheBackend(),
      bus: new CacheBus(null),
      retryCoordinator: retry,
    });
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("link down"));
    const pending = retry.runRequest({
      executor: createSafeRequestRetryExecutor({ endpoint: "/api/test/clear-cache" }),
      key: "read:clear-cache",
    });
    void pending.catch(() => undefined);

    await controller.clearAll();

    await expect(pending).rejects.toMatchObject({ name: "RetryCancelledError" });
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

  it.each([
    {
      expectedCleanup: { userId: "user-a", workspaceId: "next" },
      operation: (controller: CacheLifecycleController) => controller.authorizationFailure(),
      operationName: "authorization failure",
    },
    {
      expectedCleanup: { userId: "user-a" },
      operation: (controller: CacheLifecycleController) => controller.endSession(),
      operationName: "logout",
    },
  ])("serializes $operationName behind an in-flight scope transition", async ({ expectedCleanup, operation }) => {
    const backend = new MemoryCacheBackend();
    await backend.put({ metadata: entry({ workspaceId: "previous" }), payload: { value: "old" } });
    await backend.put({ metadata: entry({ workspaceId: "next" }), payload: { value: "new" } });
    const previousCleanup = deferred<Awaited<ReturnType<FileCacheMaintenance["clear"]>>>();
    let delayedPreviousCleanup = true;
    const fileCache: FileCacheMaintenance = {
      clear: vi.fn(async (filter) => {
        if (filter.workspaceId === "previous" && delayedPreviousCleanup) {
          delayedPreviousCleanup = false;
          return previousCleanup.promise;
        }
        return completeFileCleanup();
      }),
      diagnostics: async () => ({ available: true, bytes: 0, entryCount: 0, pendingCleanupCount: 0 }),
      initialize: async () => undefined,
      renewAccessLease: async () => undefined,
    };
    const controller = new CacheLifecycleController({ backend, bus: new CacheBus(null), fileCacheMaintenance: fileCache });
    await controller.transition({ appId: "base-shell", userId: "user-a", workspaceId: "previous" });

    const transition = controller.transition({ appId: "base-shell", userId: "user-a", workspaceId: "next" });
    await until(() => vi.mocked(fileCache.clear).mock.calls.length === 1);
    const terminatingOperation = operation(controller);

    expect(vi.mocked(fileCache.clear)).toHaveBeenCalledTimes(1);
    previousCleanup.resolve(completeFileCleanup());
    await Promise.all([transition, terminatingOperation]);

    expect(vi.mocked(fileCache.clear)).toHaveBeenNthCalledWith(2, expectedCleanup);
    expect(await backend.list({ userId: "user-a", workspaceId: "next" })).toEqual([]);
    await backend.put({ metadata: entry({ workspaceId: "next" }), payload: { value: "should-not-invalidate" } });
    await controller.handleDataChanged({ ownerAppId: "docs", resource: "records" });
    expect(await backend.list({ userId: "user-a", workspaceId: "next" })).toHaveLength(1);
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
      fileCacheAvailable: false,
      fileCacheBytes: 0,
      fileCacheEntryCount: 0,
      originQuotaBytes: 1_000,
      originUsageBytes: 200,
      pendingCleanupCount: 0,
      structuredCacheBytes: 12,
      structuredEntryCount: 1,
    });
    expect(await controller.clearAll()).toMatchObject({ removed: 1, status: "complete" });
    expect(await backend.list()).toEqual([]);
  });

  it("coordinates Storage OPFS cleanup and lease renewal with the authenticated lifecycle", async () => {
    const clear = vi.fn(async () => ({ pendingCleanupCount: 0, removed: 2, status: "complete" as const }));
    const renewAccessLease = vi.fn(async () => undefined);
    const fileCache: FileCacheMaintenance = {
      clear,
      diagnostics: async () => ({ available: true, bytes: 80, entryCount: 2, pendingCleanupCount: 0 }),
      initialize: async () => undefined,
      renewAccessLease,
    };
    const controller = new CacheLifecycleController({
      backend: new MemoryCacheBackend(),
      bus: new CacheBus(null),
      fileCacheMaintenance: fileCache,
      now: () => 1_000,
    });
    const lease = { issuedAt: 1_000, expiresAt: 5_000 };
    await controller.transition({ accessLease: lease, appId: "base-shell", userId: "user-a", workspaceId: "default" });
    expect(renewAccessLease).toHaveBeenCalledWith({ appId: "storage", userId: "user-a", workspaceId: "default" }, lease);
    expect(await controller.diagnostics()).toMatchObject({
      cacheBytes: 80,
      entryCount: 2,
      fileCacheAvailable: true,
      fileCacheBytes: 80,
      fileCacheEntryCount: 2,
    });
    await expect(controller.endSession()).resolves.toMatchObject({ removed: 2, status: "complete" });
    expect(clear).toHaveBeenLastCalledWith({ userId: "user-a" });
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

function completeFileCleanup() {
  return { pendingCleanupCount: 0, removed: 0, status: "complete" as const };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function until(condition: () => boolean, attempts = 20): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (condition()) return;
    await Promise.resolve();
  }
  throw new Error("Condition was not reached before the test deadline.");
}
