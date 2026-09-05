import { describe, expect, it } from "vitest";
import { createPwaCacheMetricsCollector, isParentDataCacheRetryMessage, PWA_DATA_CACHE_BROKER_RETRY } from "@maverick/pwa-cache";
import { PwaDataCacheRetryMetrics } from "./pwaDataCacheRetryMetrics";

describe("broker retry metrics", () => {
  const scope = { appId: "app-store", requestId: "read", networkRequestId: "network" };
  const message = {
    app_id: scope.appId, request_id: scope.requestId, network_request_id: scope.networkRequestId,
    type: PWA_DATA_CACHE_BROKER_RETRY,
    event: { attempt: 0, keyHash: "deadbeef", kind: "wait_started" as const },
  };

  it("accepts only the active app/read/network and bounded redacted event identity", () => {
    expect(isParentDataCacheRetryMessage(message, scope)).toBe(true);
    for (const field of ["app_id", "request_id", "network_request_id", "type"]) {
      expect(isParentDataCacheRetryMessage({ ...message, [field]: "foreign" }, scope)).toBe(false);
    }
    for (const event of [null, {}, { ...message.event, keyHash: "private/path" }, { ...message.event, attempt: Infinity },
      { ...message.event, attempt: -1 }, { ...message.event, attempt: 0.5 }, { ...message.event, kind: "unknown" }]) {
      expect(isParentDataCacheRetryMessage({ ...message, event }, scope)).toBe(false);
    }
  });

  it("deduplicates events, isolates equal child keys, and measures duration on the host", () => {
    let now = 1_000;
    const metrics = createPwaCacheMetricsCollector({ storage: null, now: () => now });
    const record = metrics.recordRetry.bind(metrics);
    const first = new PwaDataCacheRetryMetrics("first", record, () => now);
    const second = new PwaDataCacheRetryMetrics("second", record, () => now);
    first.receive({ ...message.event, kind: "retry_attempt", attempt: 1 }); // no wait
    first.receive(message.event);
    first.receive(message.event);
    second.receive(message.event);
    expect(metrics.snapshot().requestWait.pendingCount).toBe(2);
    now += 700;
    first.receive({ ...message.event, kind: "retry_attempt", attempt: 2 }); // out of order
    first.receive({ ...message.event, kind: "retry_attempt", attempt: 1 });
    first.receive({ ...message.event, kind: "retry_attempt", attempt: 1 });
    first.receive({ ...message.event, kind: "resolved", attempt: 1, durationMs: 999_999 });
    first.receive(message.event); // replay after completion
    first.close("cancelled");
    second.close("cancelled");
    second.receive(message.event); // late delivery after host teardown
    const snapshot = metrics.snapshot();
    expect(snapshot.requestWait).toMatchObject({ pendingCount: 0, durationObservations: 2, totalDurationMs: 1_400 });
    expect(snapshot.counters).toMatchObject({
      pwa_request_wait_started: 2, pwa_request_retry_attempt: 1,
      pwa_request_wait_resolved: 1, pwa_request_wait_cancelled: 1,
    });
    expect(JSON.stringify(snapshot)).not.toMatch(/deadbeef|first|second/);
  });

  it("bounds per-network bookkeeping and drains it on close", () => {
    const metrics = createPwaCacheMetricsCollector({ storage: null });
    const tracker = new PwaDataCacheRetryMetrics("network", metrics.recordRetry.bind(metrics));
    for (let index = 0; index < 100; index++) tracker.receive({ ...message.event, keyHash: index.toString(16).padStart(8, "0") });
    expect(metrics.snapshot().requestWait.pendingCount).toBe(16);
    tracker.close("cancelled");
    tracker.close("cancelled");
    expect(metrics.snapshot().requestWait.pendingCount).toBe(0);
    expect(metrics.snapshot().counters.pwa_request_wait_cancelled).toBe(16);
  });
});
