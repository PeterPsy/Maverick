import { IDBFactory } from "fake-indexeddb";
import { afterEach, expect, it, vi } from "vitest";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

// Independent module graphs model two tabs: no shared epoch Maps, bus or SDK
// instances. Only origin storage, IndexedDB and the browser lock service cross
// the boundary. A second wrapper in the same graph would hide this regression.
async function context() {
  vi.resetModules();
  return {
    sdk: await import("../src"),
    testing: await import("../src/testing"),
    backend: await import("../src/resilientBackend"),
    barrier: await import("../src/publicationBarrier"),
  };
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.resetModules(); });

it.each(["initialization", "quota"])("fences a writer recovering from RAM during %s across isolated contexts", async (recovery) => {
  const storage = new Map<string, string>();
  const tails = new Map<string, Promise<unknown>>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  });
  vi.stubGlobal("navigator", { locks: { request: (name: string, _options: unknown, operation: () => Promise<unknown>) => {
    const next = (tails.get(name) ?? Promise.resolve()).then(operation);
    tails.set(name, next.catch(() => undefined));
    return next;
  } } });
  const window = {};
  vi.stubGlobal("window", Object.assign(window, { top: window, self: window }));
  const writer = await context();
  const cleaner = await context();
  expect(writer.barrier.publicationGeneration).not.toBe(cleaner.barrier.publicationGeneration);
  const factory = new IDBFactory();
  const primary = new writer.testing.IndexedDbCacheBackend({ factory });
  const backend = new writer.backend.ResilientCacheBackend(primary);
  vi.spyOn(primary, "initialize").mockRejectedValueOnce(new Error("temporary IDB outage"));
  await backend.initialize();
  expect(backend.mode()).toBe("memory");
  const maintenance = recovery === "quota" ? vi.spyOn(backend, "clearForMaintenance").mockResolvedValue(0) : null;
  const entered = deferred<void>();
  const quota = deferred<boolean>();
  const client = writer.sdk.createPwaCacheHost({ appId: "docs", userId: "u", workspaceId: "w" }).createClient({
    backend, enabled: true, accessLease: { issuedAt: 0, expiresAt: 1_000 }, now: () => 100,
    quotaAdapter: { canWrite: () => { entered.resolve(); return quota.promise; }, estimate: async () => ({ supported: true, quota: 100_000, usage: 0 }) },
  }, new writer.testing.CacheBus(null));
  const resource = client.resource("review", {
    cacheApproved: true, dataClass: "workspace_internal", provenance: "app_reference",
    policyRevision: writer.sdk.LOCAL_PERSISTENCE_POLICY_REVISION, schemaRevision: "review.v1",
    freshTtlMs: 1_000, expiryTtlMs: 10_000, maxEntryBytes: 1_024, maxScopeBytes: 8_192,
    sanitize: (value: unknown) => value as { value: string },
  });
  const read = resource.readThrough("one", async () => ({ kind: "value", payload: { value: "private" }, revision: "old" }));
  await entered.promise;
  maintenance?.mockRestore();
  if (recovery === "quota") await backend.clearForMaintenance({}, { durable: true });
  expect(backend.mode()).toBe("indexeddb");
  const localAdmission = writer.barrier.publicationGeneration(backend.durabilityKey(), false);
  const lifecycle = new cleaner.sdk.CacheLifecycleController({
    backend: new cleaner.testing.IndexedDbCacheBackend({ factory }), bus: new cleaner.testing.CacheBus(null),
  });
  expect((await lifecycle.clearAll()).status).toBe("complete");
  expect(writer.barrier.publicationGeneration(backend.durabilityKey(), false)).toBe(localAdmission);
  expect(cleaner.barrier.publicationGeneration(backend.durabilityKey(), false)).not.toBe(localAdmission);
  expect(await primary.list()).toHaveLength(0);
  quota.resolve(true);
  await read;
  expect(await primary.list()).toHaveLength(0);
  expect(await resource.get("one")).toBeNull();
  await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "current" }, revision: "new" }));
  expect(await resource.get("one")).toMatchObject({ revision: "new" });
  client.dispose();
  lifecycle.dispose();
});
