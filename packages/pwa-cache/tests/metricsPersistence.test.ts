import { describe, expect, it, vi } from "vitest";
import { PWA_CACHE_METRICS_STORAGE_KEY, createPwaCacheMetricsCollector } from "../src";
import { MemoryStorage, ResetInterleavingStorage } from "./metricsTestStorage";

describe("PWA metric history and bounded retention", () => {
  it("restores valid aggregates but discards stale or malformed documents", () => {
    const storage = new MemoryStorage();
    const first = createPwaCacheMetricsCollector({ now: () => 1_000, retentionMs: 1_000, storage });
    first.recordServiceWorker("pwa_static_cache_hit");
    expect(createPwaCacheMetricsCollector({ now: () => 1_500, retentionMs: 1_000, storage })
      .snapshot().counters.pwa_static_cache_hit).toBe(1);

    expect(createPwaCacheMetricsCollector({ now: () => 2_001, retentionMs: 1_000, storage })
      .snapshot().counters.pwa_static_cache_hit).toBe(0);
    storage.setItem(PWA_CACHE_METRICS_STORAGE_KEY, JSON.stringify({ schema: "wrong" }));
    expect(createPwaCacheMetricsCollector({ now: () => 3_000, retentionMs: 1_000, storage })
      .snapshot().counters.pwa_static_cache_hit).toBe(0);

    const future = createPwaCacheMetricsCollector({ now: () => 4_000, retentionMs: 1_000, storage });
    future.recordServiceWorker("pwa_static_cache_hit");
    const writerKey = storage.writerKeys().at(-1) as string;
    const corrupted = JSON.parse(storage.getItem(writerKey) ?? "{}") as { updatedAt: number };
    corrupted.updatedAt = 5_000;
    storage.setItem(writerKey, JSON.stringify(corrupted));
    expect(createPwaCacheMetricsCollector({ now: () => 4_500, retentionMs: 1_000, storage })
      .snapshot().counters.pwa_static_cache_hit).toBe(0);
  });

  it("restores history after reload but never restores another document's pending waits", () => {
    const storage = new MemoryStorage();
    const old = createPwaCacheMetricsCollector({ collectorId: "old-document", now: () => 1_000, storage });
    old.recordRetry({ attempt: 0, keyHash: "live", kind: "wait_started", waitMs: 100 });
    const key = storage.writerKeys()[0];
    // Also cover a shard written by the previous SDK, which persisted gauges.
    const prior = JSON.parse(storage.getItem(key)!);
    prior.requestWait.pendingCount = 1;
    prior.requestWait.oldestPendingStartedAt = 1_000;
    storage.setItem(key, JSON.stringify(prior));
    const reloaded = createPwaCacheMetricsCollector({ now: () => 1_100, storage });
    expect(reloaded.snapshot()).toMatchObject({
      counters: { pwa_request_wait_started: 1 },
      requestWait: { pendingCount: 0, oldestPendingMs: null },
    });
    expect(old.snapshot().requestWait).toMatchObject({ pendingCount: 1, oldestPendingMs: 0 });
    reloaded.recordRetry({ attempt: 0, keyHash: "new", kind: "wait_started", waitMs: 100 });
    expect(reloaded.snapshot().requestWait).toMatchObject({ pendingCount: 1, oldestPendingMs: 0 });
    const current = JSON.parse(storage.getItem(storage.writerKeys().at(-1)!)!);
    expect(current.requestWait).not.toHaveProperty("pendingCount");
    expect(current.requestWait).not.toHaveProperty("oldestPendingStartedAt");
  });

  it("automatically prunes expired shards in bounded batches without needing a dashboard or reset", () => {
    const storage = new MemoryStorage();
    for (let index = 0; index < 150; index += 1) {
      createPwaCacheMetricsCollector({ now: () => 1_000, storage }).recordDataCache({ kind: "hit" });
    }
    storage.setItem("unrelated", "preserve");
    let now = 8 * 24 * 60 * 60 * 1_000;
    const collector = createPwaCacheMetricsCollector({ now: () => now, storage });
    expect(storage.writerKeys()).toHaveLength(150 - 64);
    collector.recordDataCache({ kind: "miss" });
    expect(storage.writerKeys()).toHaveLength(150 - 64 + 1);
    for (let batch = 0; batch < 3; batch += 1) {
      now += 60_000;
      collector.recordDataCache({ kind: "miss" });
    }
    expect(storage.writerKeys()).toHaveLength(1);
    expect(storage.getItem("unrelated")).toBe("preserve");
    expect(collector.snapshot().counters).toMatchObject({ pwa_data_cache_hit: 0, pwa_data_cache_miss: 4 });
  });

  it("preserves a shard refreshed while automatic pruning examines its expired bytes", () => {
    const storage = new MemoryStorage();
    let now = 1_000;
    const writer = createPwaCacheMetricsCollector({ now: () => now, storage });
    writer.recordDataCache({ kind: "hit" });
    const writerKey = storage.writerKeys()[0];
    now = 8 * 24 * 60 * 60 * 1_000;
    const read = storage.getItem.bind(storage);
    let refreshed = false;
    const spy = vi.spyOn(storage, "getItem").mockImplementation((key) => {
      const raw = read(key);
      if (key === writerKey && !refreshed) {
        refreshed = true;
        writer.recordDataCache({ kind: "miss" });
      }
      return raw;
    });
    const observer = createPwaCacheMetricsCollector({ now: () => now, storage });
    expect(observer.snapshot().counters.pwa_data_cache_miss).toBe(1);
    expect(storage.writerKeys()).toContain(writerKey);
    spy.mockRestore();
  });

  it("keeps a winning reset's newly written shard during automatic pruning", () => {
    const storage = new ResetInterleavingStorage();
    let now = 1_000;
    const writer = createPwaCacheMetricsCollector({ now: () => now, storage });
    const observer = createPwaCacheMetricsCollector({ now: () => now, storage });
    writer.recordDataCache({ kind: "hit" });
    now = 8 * 24 * 60 * 60 * 1_000;
    storage.afterResetRead = () => {
      writer.reset();
      writer.recordDataCache({ kind: "miss" });
    };
    observer.recordDataCache({ kind: "stale" });
    expect(observer.snapshot().counters.pwa_data_cache_miss).toBe(1);
  });

  it("treats denied pruning as best-effort diagnostics, not a cache failure", () => {
    const storage = new MemoryStorage();
    const spy = vi.spyOn(storage, "key").mockImplementation(() => { throw new Error("denied"); });
    const collector = createPwaCacheMetricsCollector({ now: () => 1_000, storage });
    collector.recordDataCache({ kind: "hit" });
    expect(collector.snapshot().counters.pwa_data_cache_hit).toBe(1);
    spy.mockRestore();
  });

  it("merges independent tab writers without losing either tab's counters", () => {
    const storage = new MemoryStorage();
    const tabA = createPwaCacheMetricsCollector({ collectorId: "tab-a", now: () => 1_000, storage });
    const tabB = createPwaCacheMetricsCollector({ collectorId: "tab-b", now: () => 1_000, storage });

    tabA.recordDataCache({ kind: "hit" });
    tabB.recordFileCache({ kind: "hit" });

    expect(tabA.snapshot().counters).toMatchObject({
      pwa_data_cache_hit: 1,
      pwa_file_cache_hit: 1,
    });
    expect(tabB.snapshot().counters).toMatchObject({
      pwa_data_cache_hit: 1,
      pwa_file_cache_hit: 1,
    });
  });

  it("uses a reset generation so a stale tab cannot resurrect cleared metrics", () => {
    const storage = new MemoryStorage();
    const tabA = createPwaCacheMetricsCollector({ collectorId: "tab-a", now: () => 1_000, storage });
    const tabB = createPwaCacheMetricsCollector({ collectorId: "tab-b", now: () => 1_000, storage });
    tabA.recordDataCache({ kind: "hit" });
    tabB.recordFileCache({ kind: "hit" });

    tabA.reset();
    tabB.recordFileCache({ kind: "miss" });

    expect(tabA.snapshot().counters).toMatchObject({
      pwa_data_cache_hit: 0,
      pwa_file_cache_hit: 0,
      pwa_file_cache_miss: 1,
    });
    expect(tabB.snapshot().counters).toMatchObject({
      pwa_data_cache_hit: 0,
      pwa_file_cache_hit: 0,
      pwa_file_cache_miss: 1,
    });
  });

  it("does not prune a peer event that is causally newer than the reset marker", () => {
    const storage = new ResetInterleavingStorage();
    const tabA = createPwaCacheMetricsCollector({ collectorId: "tab-a", now: () => 1_000, storage });
    const tabB = createPwaCacheMetricsCollector({ collectorId: "tab-b", now: () => 1_000, storage });
    tabB.recordFileCache({ kind: "hit" });
    storage.afterResetMarker = () => tabB.recordFileCache({ kind: "miss" });

    tabA.reset();

    expect(tabA.snapshot().counters).toMatchObject({
      pwa_file_cache_hit: 0,
      pwa_file_cache_miss: 1,
    });
  });

  it("preserves events from the winning generation when two tabs reset concurrently", () => {
    const storage = new ResetInterleavingStorage();
    const tabA = createPwaCacheMetricsCollector({ collectorId: "tab-a", now: () => 1_000, storage });
    const tabB = createPwaCacheMetricsCollector({ collectorId: "tab-b", now: () => 1_000, storage });
    tabA.recordDataCache({ kind: "hit" });
    tabB.recordFileCache({ kind: "hit" });
    storage.afterResetMarker = () => {
      tabB.reset();
      tabB.recordFileCache({ kind: "miss" });
    };

    tabA.reset();

    expect(tabA.snapshot().counters).toMatchObject({
      pwa_data_cache_hit: 0,
      pwa_file_cache_hit: 0,
      pwa_file_cache_miss: 1,
    });
    expect(tabB.snapshot().counters.pwa_file_cache_miss).toBe(1);
  });

  it("cannot prune a later reset even after observing itself as the provisional winner", () => {
    const storage = new ResetInterleavingStorage();
    const tabA = createPwaCacheMetricsCollector({ collectorId: "tab-a", now: () => 1_000, storage });
    const tabB = createPwaCacheMetricsCollector({ collectorId: "tab-b", now: () => 1_000, storage });
    tabA.recordDataCache({ kind: "hit" });
    tabB.recordFileCache({ kind: "hit" });
    storage.afterResetRead = () => {
      tabB.reset();
      tabB.recordFileCache({ kind: "miss" });
    };

    tabA.reset();

    expect(tabA.snapshot().counters).toMatchObject({
      pwa_data_cache_hit: 0,
      pwa_file_cache_hit: 0,
      pwa_file_cache_miss: 1,
    });
    expect(tabB.snapshot().counters.pwa_file_cache_miss).toBe(1);
  });
});
