import { describe, expect, it, vi } from "vitest";
import {
  LOCAL_PERSISTENCE_POLICY_REVISION,
  RetryCoordinator,
  createPwaCacheHost,
  createPwaCacheMetricsCollector,
  createSafeRequestRetryExecutor,
  type ResourceCachePolicy,
  type StorageQuotaAdapter,
} from "../src";
import { CacheBus, MemoryCacheBackend, validatedPayloadSize } from "../src/testing";

type Payload = { value: string };

function policy(overrides: Partial<ResourceCachePolicy<Payload>> = {}): ResourceCachePolicy<Payload> {
  return {
    allowStale: true,
    dataClass: "public",
    expiryTtlMs: 10_000,
    freshTtlMs: 1_000,
    maxEntryBytes: 1_024,
    maxScopeBytes: 8_192,
    policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
    provenance: "app_reference",
    revalidateOnRead: "stale",
    sanitize: (value) => {
      const candidate = value && typeof value === "object" ? value as { value?: unknown } : {};
      return typeof candidate.value === "string" ? { value: candidate.value } : null;
    },
    schemaRevision: "chaos.v1",
    ...overrides,
  };
}

function resource(backend: MemoryCacheBackend, quotaAdapter: StorageQuotaAdapter, now: () => number, overrides = {}) {
  return createPwaCacheHost({ appId: "chaos", userId: "user-a", workspaceId: "default" })
    .createClient({ backend, enabled: true, now, quotaAdapter }, new CacheBus(null))
    .resource("records", policy(overrides));
}

describe("PWA cache hardening chaos matrix", () => {
  it("keeps the authoritative network result when quota estimation fails", async () => {
    const backend = new MemoryCacheBackend();
    const quota: StorageQuotaAdapter = {
      canWrite: async () => { throw new DOMException("quota unavailable", "QuotaExceededError"); },
      estimate: async () => ({ quota: null, supported: true, usage: null }),
    };
    const subject = resource(backend, quota, () => 1_000);

    await expect(subject.readThrough("one", async () => ({
      kind: "value",
      payload: { value: "network" },
      revision: "r1",
    }))).resolves.toMatchObject({ payload: { value: "network" }, source: "network" });
    await expect(backend.list()).resolves.toEqual([]);
  });

  it("evicts least-recent entries under pressure without exceeding the declared scope", async () => {
    let now = 1_000;
    const backend = new MemoryCacheBackend();
    const quota: StorageQuotaAdapter = {
      canWrite: async () => true,
      estimate: async () => ({ quota: 1_000_000, supported: true, usage: 0 }),
    };
    const subject = resource(backend, quota, () => now, { maxEntryBytes: 32, maxScopeBytes: 40 });
    for (const id of ["oldest", "middle", "newest"]) {
      await subject.readThrough(id, async () => ({ kind: "value", payload: { value: id }, revision: `r-${id}` }));
      now += 100;
    }

    const entries = await backend.list();
    expect(entries.reduce((total, entry) => total + entry.sizeBytes, 0)).toBeLessThanOrEqual(40);
    expect(entries.some((entry) => entry.entityId === "oldest")).toBe(false);
    expect(entries.some((entry) => entry.entityId === "newest")).toBe(true);
  });

  it("deletes a corrupted persisted payload before it can reach rendering", async () => {
    const backend = new MemoryCacheBackend();
    const quota: StorageQuotaAdapter = {
      canWrite: async () => true,
      estimate: async () => ({ quota: 1_000_000, supported: true, usage: 0 }),
    };
    const subject = resource(backend, quota, () => 1_000);
    await subject.readThrough("one", async () => ({ kind: "value", payload: { value: "safe" }, revision: "r1" }));
    const [metadata] = await backend.list();
    await backend.put({
      metadata: { ...metadata, sizeBytes: validatedPayloadSize({ html: "<script>poison()</script>" }) },
      payload: { html: "<script>poison()</script>" },
    });

    await expect(subject.get("one")).resolves.toBeNull();
    await expect(backend.list()).resolves.toEqual([]);
  });

  it("single-flights intermittent transport retries and records one bounded wait", async () => {
    vi.useFakeTimers();
    const metrics = createPwaCacheMetricsCollector({ now: Date.now, storage: null });
    const coordinator = new RetryCoordinator({
      random: () => 0.5,
      telemetry: (event) => metrics.recordRetry(event),
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("link down"))
      .mockRejectedValueOnce(new TypeError("link flapped"))
      .mockResolvedValueOnce(new Response(JSON.stringify("ready"), {
        headers: { "Content-Type": "application/json" },
      }));
    const executor = createSafeRequestRetryExecutor({ endpoint: "/api/test/intermittent-read" });

    const first = coordinator.runRequest<string>({ executor, key: "intermittent-read" });
    const second = coordinator.runRequest<string>({ executor, key: "intermittent-read" });
    expect(second).toBe(first);
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(2_000);

    await expect(first).resolves.toBe("ready");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(metrics.snapshot().counters).toMatchObject({
      pwa_request_retry_attempt: 2,
      pwa_request_wait_resolved: 1,
      pwa_request_wait_started: 1,
    });
    vi.restoreAllMocks();
    vi.useRealTimers();
  });
});
