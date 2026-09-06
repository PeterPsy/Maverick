import { describe, expect, it } from "vitest";
import { createPwaCacheMetricsCollector } from "../src";
import { MemoryStorage } from "./metricsTestStorage";

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
    const persisted = storage.serializedValues();
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
    expect(storage.serializedValues()).not.toContain("opaque-");
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

  it("keeps real pending waits when only the historical retention window rolls", () => {
    let now = 1_000;
    const collector = createPwaCacheMetricsCollector({ now: () => now, retentionMs: 1_000, storage: null });
    collector.recordRetry({ attempt: 0, keyHash: "live", kind: "wait_started", waitMs: 100 });
    now = 3_000;
    expect(collector.snapshot().requestWait).toMatchObject({ pendingCount: 1, oldestPendingMs: 2_000 });
    collector.recordRetry({ attempt: 0, keyHash: "live", kind: "resolved" });
    expect(collector.snapshot().requestWait).toMatchObject({ pendingCount: 0, oldestPendingMs: null });
  });

  it("rejects arbitrary service-worker metric names", () => {
    const collector = createPwaCacheMetricsCollector({ storage: null });

    expect(collector.recordServiceWorker("pwa_static_cache_hit")).toBe(true);
    expect(collector.recordServiceWorker("pwa_static_cache_hit:https://secret.test")).toBe(false);
    expect(collector.snapshot().counters.pwa_static_cache_hit).toBe(1);
  });

  it("separates local cache failures from explicit revalidation loader errors", () => {
    const collector = createPwaCacheMetricsCollector({ storage: null });

    collector.recordDataCache({ kind: "error", reason: "budget-or-quota" });
    collector.recordDataCache({ kind: "error", reason: "MaverickTransportError", revalidation: true });

    expect(collector.snapshot().counters.pwa_data_cache_error).toBe(1);
    expect(collector.snapshot().counters.pwa_revalidate_error).toBe(1);
  });
});
