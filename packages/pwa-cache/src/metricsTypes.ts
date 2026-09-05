import type {
  CacheTelemetryEvent,
  StorageQuotaTelemetryEvent,
} from "./types";
import type { FileCacheTelemetryEvent } from "./fileCacheTypes";
import type { RetryTelemetryEvent } from "./retryPolicy";

export const PWA_CACHE_METRICS_SCHEMA = "maverick.pwa-cache-metrics.v1";
export const PWA_CACHE_METRICS_STORAGE_KEY = "maverick.pwa-cache.metrics.v1";

export const PWA_CACHE_COUNTER_METRICS = [
  "pwa_static_cache_hit",
  "pwa_static_cache_miss",
  "pwa_static_cache_error",
  "pwa_data_cache_hit",
  "pwa_data_cache_miss",
  "pwa_data_cache_stale",
  "pwa_data_cache_expired",
  "pwa_revalidate_not_modified",
  "pwa_revalidate_modified",
  "pwa_revalidate_error",
  "pwa_file_cache_write",
  "pwa_file_cache_ready",
  "pwa_file_cache_hit",
  "pwa_file_cache_miss",
  "pwa_file_cache_error",
  "pwa_file_cache_evict",
  "pwa_quota_usage",
  "pwa_quota_estimate",
  "pwa_quota_error",
  "pwa_eviction_count",
  "pwa_eviction_bytes",
  "pwa_sw_install",
  "pwa_sw_update",
  "pwa_sw_recovery",
  "pwa_sw_error",
  "pwa_request_wait_started",
  "pwa_request_wait_resolved",
  "pwa_request_wait_cancelled",
  "pwa_request_wait_duration_ms",
  "pwa_request_retry_attempt",
] as const;

export type PwaCacheCounterMetric = typeof PWA_CACHE_COUNTER_METRICS[number];

export type PwaServiceWorkerMetric = Extract<PwaCacheCounterMetric,
  | "pwa_static_cache_hit"
  | "pwa_static_cache_miss"
  | "pwa_static_cache_error"
  | "pwa_sw_install"
  | "pwa_sw_update"
  | "pwa_sw_recovery"
  | "pwa_sw_error"
>;

export type PwaCacheMetricsSnapshot = {
  schema: typeof PWA_CACHE_METRICS_SCHEMA;
  counters: Record<PwaCacheCounterMetric, number>;
  quota: {
    lastEstimatedAt: number | null;
    quotaBytes: number | null;
    supported: boolean | null;
    usageBytes: number | null;
  };
  requestWait: {
    averageDurationMs: number;
    durationObservations: number;
    maxDurationMs: number;
    oldestPendingMs: number | null;
    pendingCount: number;
    totalDurationMs: number;
  };
  updatedAt: number;
  windowStartedAt: number;
};

export type PwaCacheMetricsStorage = Pick<Storage, "getItem" | "removeItem" | "setItem">;

export type PwaCacheMetricsCollectorOptions = {
  now?: () => number;
  retentionMs?: number;
  storage?: PwaCacheMetricsStorage | null;
  storageKey?: string;
};

export type {
  CacheTelemetryEvent,
  FileCacheTelemetryEvent,
  RetryTelemetryEvent,
  StorageQuotaTelemetryEvent,
};
