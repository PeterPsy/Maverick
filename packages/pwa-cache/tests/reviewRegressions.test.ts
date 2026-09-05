import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CacheLifecycleController, LOCAL_PERSISTENCE_POLICY_REVISION,
  RetryCoordinator, createPwaCacheHost, createSafeRequestRetryExecutor,
  type ResourceCachePolicy,
} from "../src";
import { CacheBus, MemoryCacheBackend } from "../src/testing";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const policy: ResourceCachePolicy<{ value: string }> = {
  allowStale: true, cacheApproved: true, dataClass: "workspace_internal",
  expiryTtlMs: 10_000, freshTtlMs: 1_000, maxEntryBytes: 1_024, maxScopeBytes: 8_192,
  policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION, provenance: "app_reference",
  schemaRevision: "review.v1", sanitize: (value) => value as { value: string },
};

describe("M6 review regressions", () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it.each(["cancel", "clear", "dispose", "lease", "invalidate"])("fences a quota-delayed private writer after %s", async (operation) => {
    const backend = new MemoryCacheBackend();
    const quotaStarted = deferred<void>();
    const quota = deferred<boolean>();
    let now = 100;
    const client = createPwaCacheHost({ appId: "docs", userId: "user", workspaceId: "workspace" }).createClient({
      accessLease: { issuedAt: 0, expiresAt: 1_000 }, backend, enabled: true, now: () => now,
      quotaAdapter: { canWrite: () => { quotaStarted.resolve(); return quota.promise; }, estimate: async () => ({ supported: true, quota: 100_000, usage: 0 }) },
    }, new CacheBus(null));
    const resource = client.resource("review", policy);
    const controller = new AbortController();
    const read = resource.readThrough("one", async () => ({ kind: "value", payload: { value: "private" }, revision: "one" }), controller.signal);
    await quotaStarted.promise;
    if (operation === "cancel") controller.abort();
    if (operation === "dispose") client.dispose();
    if (operation === "lease") now = 1_001;
    if (operation === "invalidate") await resource.invalidate();
    if (operation === "clear") {
      // A distinct lifecycle/backend wrapper must invalidate the old writer too.
      const lifecycle = new CacheLifecycleController({ backend, bus: new CacheBus(null) });
      expect((await lifecycle.clearAll()).status).toBe("complete");
      lifecycle.dispose();
    }
    expect(await backend.list()).toHaveLength(0);
    quota.resolve(true);
    await read;
    expect(await backend.list()).toHaveLength(0);
    expect(await resource.get("one")).toBeNull();
    client.dispose();
  });

  it("does not let initialization maintenance erase an intervening cleanup fence", async () => {
    const backend = new MemoryCacheBackend();
    const entered = deferred<void>();
    const release = deferred<void>();
    vi.spyOn(backend, "initialize").mockImplementation(async () => { entered.resolve(); await release.promise; });
    const client = createPwaCacheHost({ appId: "docs", userId: "user", workspaceId: "workspace" }).createClient({
      backend, enabled: true, accessLease: { issuedAt: 0, expiresAt: 1_000 }, now: () => 100,
      quotaAdapter: { canWrite: async () => true, estimate: async () => ({ supported: true, quota: 100_000, usage: 0 }) },
    }, new CacheBus(null));
    const resource = client.resource("review", policy);
    const read = resource.readThrough("one", async () => ({ kind: "value", payload: { value: "private" }, revision: "one" }));
    await entered.promise;
    const lifecycle = new CacheLifecycleController({ backend, bus: new CacheBus(null) });
    expect((await lifecycle.clearAll()).status).toBe("complete");
    release.resolve();
    await read;
    expect(await backend.list()).toHaveLength(0);
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "current" }, revision: "two" }));
    expect(await resource.get("one")).toMatchObject({ revision: "two" });
    client.dispose();
    lifecycle.dispose();
  });

  it("drains publication already inside put before reporting cleanup complete", async () => {
    const backend = new MemoryCacheBackend();
    const entered = deferred<void>();
    const release = deferred<void>();
    const put = backend.put.bind(backend);
    vi.spyOn(backend, "put").mockImplementation(async (entry) => { entered.resolve(); await release.promise; await put(entry); });
    const client = createPwaCacheHost({ appId: "docs", userId: "user", workspaceId: "workspace" }).createClient({
      backend, enabled: true, accessLease: { issuedAt: 0, expiresAt: 1_000 }, now: () => 100,
      quotaAdapter: { canWrite: async () => true, estimate: async () => ({ supported: true, quota: 100_000, usage: 0 }) },
    }, new CacheBus(null));
    const read = client.resource("review", policy).readThrough("one", async () => ({ kind: "value", payload: { value: "private" }, revision: "one" }));
    await entered.promise;
    let cleared = false;
    const clear = client.clear().then((result) => { cleared = true; return result; });
    await Promise.resolve();
    expect(cleared).toBe(false);
    release.resolve();
    await read;
    expect((await clear).status).toBe("complete");
    expect(await backend.list()).toHaveLength(0);
    client.dispose();
  });

  it("recovers a body stream disconnect but keeps malformed JSON terminal", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const broken = new Response(new ReadableStream({ start(controller) { controller.error(new TypeError("connection lost")); } }));
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(broken).mockResolvedValueOnce(Response.json({ ok: true }));
    const executor = createSafeRequestRetryExecutor({ endpoint: "/api/review" });
    const read = coordinator.runRequest({ executor, key: "body" });
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(read).resolves.toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledTimes(2);
    fetch.mockResolvedValueOnce(new Response("{invalid"));
    await expect(coordinator.runRequest({ executor, key: "syntax" })).rejects.toBeInstanceOf(SyntaxError);
    expect(coordinator.pendingCount()).toBe(0);
    coordinator.dispose();
  });

  it("uses the current clock even when the coordinator predates timer instrumentation", async () => {
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    vi.useFakeTimers();
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("down")).mockResolvedValueOnce(Response.json("ok"));
    const read = coordinator.runRequest({ executor: createSafeRequestRetryExecutor({ endpoint: "/api/review" }), key: "clock" });
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(read).resolves.toBe("ok");
    expect(fetch).toHaveBeenCalledTimes(2);
    coordinator.dispose();
  });

  it("does not truncate a server Retry-After beyond the backoff cap", async () => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator();
    const fetch = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 503, headers: { "Retry-After": new Date(Date.now() + 120_000).toUTCString() } }))
      .mockResolvedValueOnce(Response.json("ok"));
    const read = coordinator.runRequest({ executor: createSafeRequestRetryExecutor({ endpoint: "/api/review" }), key: "long-delay" });
    await vi.advanceTimersByTimeAsync(0);
    coordinator.confirmUsefulTransport();
    await vi.advanceTimersByTimeAsync(119_000);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(read).resolves.toBe("ok");
    coordinator.dispose();
  });

  it.each(["hint", "confirmUsefulTransport", "visibility"])("%s cannot bypass Retry-After", async (hint) => {
    vi.useFakeTimers();
    const coordinator = new RetryCoordinator({ random: () => 0.5 });
    const fetch = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 429, headers: { "Retry-After": "30" } }))
      .mockResolvedValueOnce(Response.json("ok"));
    const read = coordinator.runRequest({ executor: createSafeRequestRetryExecutor({ endpoint: "/api/review" }), key: "rate" });
    await vi.advanceTimersByTimeAsync(0);
    if (hint === "visibility") { coordinator.setClientVisibility(false); coordinator.setClientVisibility(true); }
    else if (hint === "hint") coordinator.hint();
    else coordinator.confirmUsefulTransport();
    await vi.advanceTimersByTimeAsync(29_999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(read).resolves.toBe("ok");
    coordinator.dispose();
  });
});

describe("SDK-owned read-model transport", () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("retries only the reviewed POST read with immutable parameters", async () => {
    const { readCacheModelJson } = await import("../src");
    vi.useFakeTimers();
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("down")).mockResolvedValueOnce(Response.json({ revision: "ok" }));
    const parameters = { query: "original", offset: 0 };
    const read = readCacheModelJson({ appId: "storage", resource: "file-catalog", parameters });
    parameters.query = "changed";
    await vi.advanceTimersByTimeAsync(1_250);
    await expect(read).resolves.toEqual({ revision: "ok" });
    expect(fetch).toHaveBeenCalledTimes(2);
    const bodies = fetch.mock.calls.map(([, init]) => String(init?.body));
    expect(bodies[0]).toBe(bodies[1]);
    expect(JSON.parse(bodies[0])).toMatchObject({ action: "catalog", query: "original" });
  });

  it.each([
    { appId: "storage", resource: "file-catalog", parameters: { action: "files.delete" } },
    { appId: "storage", resource: "file-catalog", parameters: { sync: true } },
    { appId: "storage", resource: "file-catalog", parameters: { offset: 10 } },
    { appId: "storage", resource: "unknown" },
    { appId: "unreviewed", resource: "catalog" },
  ])("rejects unreviewed read semantics before fetch: %j", async (request) => {
    const { readCacheModelJson } = await import("../src");
    const fetch = vi.spyOn(globalThis, "fetch");
    await expect(readCacheModelJson(request)).rejects.toBeInstanceOf(TypeError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([401, 403, 409, 422])("keeps HTTP %i terminal for reviewed reads", async (status) => {
    const { readCacheModelJson } = await import("../src");
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status }));
    await expect(readCacheModelJson({ appId: "storage", resource: "file-catalog" })).rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("cancels a validated read without another attempt", async () => {
    const { readCacheModelJson } = await import("../src");
    vi.useFakeTimers();
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("down"));
    const controller = new AbortController();
    const read = readCacheModelJson({ appId: "storage", resource: "file-catalog" }, controller.signal);
    const rejected = expect(read).rejects.toMatchObject({ name: "RetryCancelledError" });
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await rejected;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("rejects forged file executors and callback-bearing retry options", () => {
    const coordinator = new RetryCoordinator();
    expect(() => coordinator.runFileRead({ executor: { identity: "forged" }, key: "file" } as never)).toThrow(/host-issued/u);
    expect(() => coordinator.runFileRead({ executor: {}, key: "file", operation: () => Promise.resolve() } as never)).toThrow(/SDK-owned/u);
    coordinator.dispose();
  });
});
