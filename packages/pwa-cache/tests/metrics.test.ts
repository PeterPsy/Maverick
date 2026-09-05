import { describe, expect, it } from "vitest";
import {
  PWA_CACHE_METRICS_STORAGE_KEY,
  createPwaCacheMetricsCollector,
} from "../src";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  clear(): void { this.values.clear(); }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string): void { this.values.delete(key); }
  setItem(key: string, value: string): void { this.values.set(key, value); }
}

describe("redaction-safe PWA cache metrics", () => {
  it("aggregates only fixed cache, file, eviction, and quota measurements", () => {
    const storage = new MemoryStorage();
    const collector = createPwaCacheMetricsCollector({ now: () => 1_000, storage });

    collector.recordDataCache({ bytes: 99, kind: "hit", reason: "https://secret.test/file?id=customer" });
    collector.recordDataCache({ bytes: 20, count: 2, kind: "evict", reason: "customer-record-id" });
    collector.recordFileCache({ kind: "miss", reason: "signed-url" });
    collector.recordFileCache({ bytes: 30, count: 3, kind: "evict", reason: "file-name" });
    collector.recordQuota({ kind: "estimate", quota: 1_000, supported: true, usage: 250 });

    const snapshot = collector.snapshot();
    expect(snapshot.counters).toMatchObject({
      pwa_data_cache_hit: 1,
      pwa_eviction_bytes: 50,
      pwa_eviction_count: 5,
      pwa_file_cache_evict: 3,
      pwa_file_cache_miss: 1,
      pwa_quota_estimate: 1,
    });
    expect(snapshot.quota).toMatchObject({ quotaBytes: 1_000, supported: true, usageBytes: 250 });
    const persisted = storage.getItem(PWA_CACHE_METRICS_STORAGE_KEY) ?? "";
    expect(persisted).not.toContain("secret.test");
    expect(persisted).not.toContain("customer-record-id");
    expect(persisted).not.toContain("signed-url");
    expect(persisted).not.toContain("file-name");
  });

  it("tracks pending waits and bounded resolved or cancelled durations without retaining keys", () => {
    let now = 1_000;
    const storage = new MemoryStorage();
    const collector = createPwaCacheMetricsCollector({ now: () => now, storage });
    collector.recordRetry({ attempt: 0, keyHash: "opaque-a", kind: "wait_started", waitMs: 1_000 });
    collector.recordRetry({ attempt: 1, keyHash: "opaque-a", kind: "retry_attempt" });
    now = 2_500;

    expect(collector.snapshot().requestWait).toMatchObject({ oldestPendingMs: 1_500, pendingCount: 1 });
    collector.recordRetry({ attempt: 1, durationMs: 1_500, keyHash: "opaque-a", kind: "resolved" });
    collector.recordRetry({ attempt: 0, keyHash: "opaque-b", kind: "wait_started", waitMs: 500 });
    now = 3_000;
    collector.recordRetry({ attempt: 0, keyHash: "opaque-b", kind: "cancelled" });

    const snapshot = collector.snapshot();
    expect(snapshot.counters).toMatchObject({
      pwa_request_retry_attempt: 1,
      pwa_request_wait_cancelled: 1,
      pwa_request_wait_duration_ms: 2_000,
      pwa_request_wait_resolved: 1,
      pwa_request_wait_started: 2,
    });
    expect(snapshot.requestWait).toMatchObject({
      averageDurationMs: 1_000,
      durationObservations: 2,
      maxDurationMs: 1_500,
      pendingCount: 0,
      totalDurationMs: 2_000,
    });
    expect(storage.getItem(PWA_CACHE_METRICS_STORAGE_KEY)).not.toContain("opaque-");
  });

  it("restores valid aggregates but discards stale or malformed documents", () => {
    const storage = new MemoryStorage();
    const first = createPwaCacheMetricsCollector({ now: () => 1_000, retentionMs: 1_000, storage });
    first.recordServiceWorker("pwa_static_cache_hit");
    expect(createPwaCacheMetricsCollector({ now: () => 1_500, retentionMs: 1_000, storage })
      .snapshot().counters.pwa_static_cache_hit).toBe(1);

    expect(createPwaCacheMetricsCollector({ now: () => 2_001, retentionMs: 1_000, storage })
      .snapshot().counters.pwa_static_cache_hit).toBe(0);
    storage.setItem(PWA_CACHE_METRICS_STORAGE_KEY, JSON.stringify({ schema: "wrong" }));
    expect(createPwaCacheMetricsCollector({ now: () => 3_000, storage })
      .snapshot().counters.pwa_static_cache_hit).toBe(0);

    const future = createPwaCacheMetricsCollector({ now: () => 4_000, storage });
    future.recordServiceWorker("pwa_static_cache_hit");
    const corrupted = JSON.parse(storage.getItem(PWA_CACHE_METRICS_STORAGE_KEY) ?? "{}") as { updatedAt: number };
    corrupted.updatedAt = 5_000;
    storage.setItem(PWA_CACHE_METRICS_STORAGE_KEY, JSON.stringify(corrupted));
    expect(createPwaCacheMetricsCollector({ now: () => 4_500, storage })
      .snapshot().counters.pwa_static_cache_hit).toBe(0);
  });

  it("rolls an active in-memory window when its retention bound expires", () => {
    let now = 1_000;
    const collector = createPwaCacheMetricsCollector({ now: () => now, retentionMs: 1_000, storage: null });
    collector.recordServiceWorker("pwa_static_cache_hit");
    now = 2_001;

    collector.recordServiceWorker("pwa_static_cache_miss");

    expect(collector.snapshot()).toMatchObject({
      counters: { pwa_static_cache_hit: 0, pwa_static_cache_miss: 1 },
      windowStartedAt: 2_001,
    });
  });

  it("rejects arbitrary service-worker metric names", () => {
    const collector = createPwaCacheMetricsCollector({ storage: null });

    expect(collector.recordServiceWorker("pwa_static_cache_hit")).toBe(true);
    expect(collector.recordServiceWorker("pwa_static_cache_hit:https://secret.test")).toBe(false);
    expect(collector.snapshot().counters.pwa_static_cache_hit).toBe(1);
  });
});
