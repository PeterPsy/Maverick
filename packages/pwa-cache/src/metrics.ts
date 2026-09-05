import {
  PWA_CACHE_COUNTER_METRICS,
  PWA_CACHE_METRICS_SCHEMA,
  PWA_CACHE_METRICS_STORAGE_KEY,
  type CacheTelemetryEvent,
  type FileCacheTelemetryEvent,
  type PwaCacheCounterMetric,
  type PwaCacheMetricsCollectorOptions,
  type PwaCacheMetricsSnapshot,
  type PwaServiceWorkerMetric,
  type RetryTelemetryEvent,
  type StorageQuotaTelemetryEvent,
} from "./metricsTypes";
import {
  MetricsShardPersistence,
  browserStorage,
  emptyCounters,
  emptyQuota,
  emptyWaitDurations,
  finiteBytes,
  finiteInteger,
  finiteTimestamp,
  positive,
  positiveInteger,
  type PersistedMetricsShard,
} from "./metricsPersistence";
import { aggregateMetricsShards } from "./metricsAggregation";

const DEFAULT_RETENTION_MS = 7 * 24 * 60 * 60 * 1_000;
const MAX_PENDING_KEYS = 4_096;
const MAX_DURATION_MS = 24 * 60 * 60 * 1_000;
const COUNTER_NAMES = new Set<string>(PWA_CACHE_COUNTER_METRICS);

export class PwaCacheMetricsCollector {
  private counters = emptyCounters();
  private readonly now: () => number;
  private readonly pendingWaits = new Map<string, number>();
  private quota: PwaCacheMetricsSnapshot["quota"] = emptyQuota();
  private readonly retentionMs: number;
  private readonly persistence: MetricsShardPersistence | null;
  private resetId = "initial";
  private updatedAt: number;
  private waitDurations = emptyWaitDurations();
  private windowStartedAt: number;

  constructor(options: PwaCacheMetricsCollectorOptions = {}) {
    this.now = options.now ?? Date.now;
    this.retentionMs = positive(options.retentionMs, DEFAULT_RETENTION_MS);
    const storageKey = options.storageKey?.trim() || PWA_CACHE_METRICS_STORAGE_KEY;
    const storage = options.storage === undefined ? browserStorage() : options.storage;
    this.persistence = storage
      ? new MetricsShardPersistence(storage, storageKey, options.collectorId)
      : null;
    const timestamp = finiteTimestamp(this.now(), Date.now());
    const reset = this.persistence?.currentReset();
    this.resetId = reset?.resetId ?? this.resetId;
    this.windowStartedAt = reset && reset.resetAt <= timestamp && reset.resetAt > 0
      ? reset.resetAt
      : timestamp;
    this.updatedAt = timestamp;
    const restored = this.persistence?.loadOwn(timestamp, this.retentionMs, this.resetId);
    if (restored) this.restoreOwn(restored);
  }

  recordDataCache(event: CacheTelemetryEvent): void {
    this.ensureCurrentWindow();
    const metric = dataCacheMetric(event);
    if (metric) this.increment(metric);
    if (event.kind === "evict") this.recordEviction(event.count, event.bytes);
  }

  recordFileCache(event: FileCacheTelemetryEvent): void {
    this.ensureCurrentWindow();
    const metric = fileCacheMetric(event);
    if (metric) this.increment(metric, event.kind === "evict" ? event.count : undefined);
    if (event.kind === "evict") this.recordEviction(event.count, event.bytes);
  }

  recordQuota(event: StorageQuotaTelemetryEvent): void {
    this.ensureCurrentWindow();
    if (event.kind === "error") {
      this.increment("pwa_quota_error");
      return;
    }
    this.quota = {
      lastEstimatedAt: finiteTimestamp(this.now(), this.updatedAt),
      quotaBytes: finiteBytes(event.quota),
      supported: event.supported,
      usageBytes: finiteBytes(event.usage),
    };
    if (event.usage !== null) this.increment("pwa_quota_usage");
    this.increment("pwa_quota_estimate");
  }

  recordRetry(event: RetryTelemetryEvent): void {
    this.ensureCurrentWindow();
    const key = validPendingKey(event.keyHash) ? event.keyHash : null;
    if (event.kind === "retry_attempt") {
      this.increment("pwa_request_retry_attempt");
      return;
    }
    if (!key) return;
    if (event.kind === "wait_started") {
      if (!this.pendingWaits.has(key) && this.pendingWaits.size < MAX_PENDING_KEYS) {
        this.pendingWaits.set(key, finiteTimestamp(this.now(), this.updatedAt));
        this.increment("pwa_request_wait_started");
      }
      return;
    }
    const startedAt = this.pendingWaits.get(key);
    if (startedAt === undefined) return;
    this.pendingWaits.delete(key);
    this.increment(event.kind === "cancelled"
      ? "pwa_request_wait_cancelled"
      : "pwa_request_wait_resolved");
    this.observeWaitDuration(event.durationMs ?? (this.now() - startedAt));
  }

  recordServiceWorker(value: unknown): boolean {
    if (!isServiceWorkerMetric(value)) return false;
    this.ensureCurrentWindow();
    this.increment(value);
    return true;
  }

  snapshot(): PwaCacheMetricsSnapshot {
    const timestamp = this.ensureCurrentWindow();
    const own = this.persistedShard();
    const peers = this.persistence?.readPeers(timestamp, this.retentionMs, this.resetId) ?? [];
    return aggregateMetricsShards([own, ...peers], timestamp);
  }

  reset(): void {
    const timestamp = finiteTimestamp(this.now(), Date.now());
    const previousResetId = this.resetId;
    const marker = this.persistence?.reset(timestamp);
    if (marker) this.resetId = marker.resetId;
    this.resetState(timestamp);
    this.persistence?.removeOwn(previousResetId);
    this.persist();
  }

  private increment(metric: PwaCacheCounterMetric, amount?: number): void {
    const delta = amount === undefined ? 1 : finiteInteger(amount, 0);
    if (delta === 0) return;
    this.counters[metric] = Math.min(Number.MAX_SAFE_INTEGER, this.counters[metric] + delta);
    this.changed();
  }

  private ensureCurrentWindow(): number {
    const timestamp = finiteTimestamp(this.now(), this.updatedAt);
    this.synchronizeReset(timestamp);
    if (timestamp < this.windowStartedAt || timestamp - this.windowStartedAt > this.retentionMs) {
      this.resetState(timestamp);
      this.persistence?.removeOwn(this.resetId);
    }
    return timestamp;
  }

  private resetState(timestamp: number): void {
    this.counters = emptyCounters();
    this.pendingWaits.clear();
    this.quota = emptyQuota();
    this.waitDurations = emptyWaitDurations();
    this.updatedAt = timestamp;
    this.windowStartedAt = timestamp;
  }

  private observeWaitDuration(value: number): void {
    const duration = Math.min(MAX_DURATION_MS, Math.max(0, finiteInteger(value, 0)));
    this.waitDurations.durationObservations += 1;
    this.waitDurations.totalDurationMs = Math.min(
      Number.MAX_SAFE_INTEGER,
      this.waitDurations.totalDurationMs + duration,
    );
    this.waitDurations.maxDurationMs = Math.max(this.waitDurations.maxDurationMs, duration);
    this.counters.pwa_request_wait_duration_ms = Math.min(
      Number.MAX_SAFE_INTEGER,
      this.counters.pwa_request_wait_duration_ms + duration,
    );
    this.changed();
  }

  private recordEviction(count: number | undefined, bytes: number | undefined): void {
    this.increment("pwa_eviction_count", count);
    const byteCount = positiveInteger(bytes, 0);
    if (byteCount > 0) this.increment("pwa_eviction_bytes", byteCount);
  }

  private changed(): void {
    this.updatedAt = finiteTimestamp(this.now(), this.updatedAt);
    this.persist();
  }

  private persist(): void {
    this.persistence?.persist(this.persistedShard());
  }

  private persistedShard(): PersistedMetricsShard {
    const pendingStarts = [...this.pendingWaits.values()];
    return {
      schema: PWA_CACHE_METRICS_SCHEMA,
      collectorId: this.persistence?.collectorId ?? "memory",
      counters: { ...this.counters },
      quota: { ...this.quota },
      requestWait: {
        ...this.waitDurations,
        averageDurationMs: this.waitDurations.durationObservations > 0
          ? Math.round(this.waitDurations.totalDurationMs / this.waitDurations.durationObservations)
          : 0,
        oldestPendingStartedAt: pendingStarts.length ? Math.min(...pendingStarts) : null,
        pendingCount: pendingStarts.length,
      },
      resetId: this.resetId,
      updatedAt: this.updatedAt,
      windowStartedAt: this.windowStartedAt,
    };
  }

  private restoreOwn(restored: PersistedMetricsShard): void {
    this.counters = restored.counters;
    this.quota = restored.quota;
    this.updatedAt = restored.updatedAt;
    this.waitDurations = restored.requestWait;
    this.windowStartedAt = restored.windowStartedAt;
  }

  private synchronizeReset(timestamp: number): void {
    const marker = this.persistence?.currentReset();
    if (!marker || marker.resetId === this.resetId) return;
    const previousResetId = this.resetId;
    this.resetId = marker.resetId;
    this.resetState(marker.resetAt <= timestamp ? marker.resetAt : timestamp);
    this.persistence?.removeOwn(previousResetId);
  }
}

export function createPwaCacheMetricsCollector(
  options: PwaCacheMetricsCollectorOptions = {},
): PwaCacheMetricsCollector {
  return new PwaCacheMetricsCollector(options);
}

function dataCacheMetric(event: CacheTelemetryEvent): PwaCacheCounterMetric | null {
  if (event.kind === "hit") return "pwa_data_cache_hit";
  if (event.kind === "miss") return "pwa_data_cache_miss";
  if (event.kind === "stale") return "pwa_data_cache_stale";
  if (event.kind === "expired") return "pwa_data_cache_expired";
  if (event.kind === "not_modified") return "pwa_revalidate_not_modified";
  if (event.kind === "write" && event.revalidation === true) return "pwa_revalidate_modified";
  if (event.kind === "error") return event.revalidation === true
    ? "pwa_revalidate_error"
    : "pwa_data_cache_error";
  return null;
}

function fileCacheMetric(event: FileCacheTelemetryEvent): PwaCacheCounterMetric | null {
  if (event.kind === "write") return "pwa_file_cache_write";
  if (event.kind === "ready") return "pwa_file_cache_ready";
  if (event.kind === "hit") return "pwa_file_cache_hit";
  if (event.kind === "miss") return "pwa_file_cache_miss";
  if (event.kind === "error") return "pwa_file_cache_error";
  if (event.kind === "evict") return "pwa_file_cache_evict";
  return null;
}

function isServiceWorkerMetric(value: unknown): value is PwaServiceWorkerMetric {
  return typeof value === "string"
    && COUNTER_NAMES.has(value)
    && (value.startsWith("pwa_static_cache_") || value.startsWith("pwa_sw_"));
}

function validPendingKey(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 128;
}
