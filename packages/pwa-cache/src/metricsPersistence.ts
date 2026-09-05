import {
  PWA_CACHE_COUNTER_METRICS,
  PWA_CACHE_METRICS_SCHEMA,
  type PwaCacheCounterMetric,
  type PwaCacheMetricsSnapshot,
  type PwaCacheMetricsStorage,
} from "./metricsTypes";

export type PersistedMetrics = Omit<PwaCacheMetricsSnapshot, "requestWait"> & {
  requestWait: Omit<PwaCacheMetricsSnapshot["requestWait"], "oldestPendingMs" | "pendingCount">;
};

export function parsePersistedMetrics(raw: string): PersistedMetrics | null {
  const value = JSON.parse(raw) as Partial<PersistedMetrics>;
  if (!value || value.schema !== PWA_CACHE_METRICS_SCHEMA || !plainObject(value.counters)
      || !plainObject(value.quota) || !plainObject(value.requestWait)) return null;
  const counters = emptyCounters();
  for (const name of PWA_CACHE_COUNTER_METRICS) {
    counters[name] = finiteInteger(value.counters[name], 0);
  }
  const windowStartedAt = finiteNumber(value.windowStartedAt);
  const updatedAt = finiteNumber(value.updatedAt);
  if (windowStartedAt === null || updatedAt === null) return null;
  return {
    schema: PWA_CACHE_METRICS_SCHEMA,
    counters,
    quota: {
      lastEstimatedAt: optionalFiniteNumber(value.quota.lastEstimatedAt),
      quotaBytes: optionalFiniteNumber(value.quota.quotaBytes),
      supported: typeof value.quota.supported === "boolean" ? value.quota.supported : null,
      usageBytes: optionalFiniteNumber(value.quota.usageBytes),
    },
    requestWait: {
      averageDurationMs: finiteInteger(value.requestWait.averageDurationMs, 0),
      durationObservations: finiteInteger(value.requestWait.durationObservations, 0),
      maxDurationMs: finiteInteger(value.requestWait.maxDurationMs, 0),
      totalDurationMs: finiteInteger(value.requestWait.totalDurationMs, 0),
    },
    updatedAt,
    windowStartedAt,
  };
}

export function emptyCounters(): Record<PwaCacheCounterMetric, number> {
  return Object.fromEntries(PWA_CACHE_COUNTER_METRICS.map((name) => [name, 0])) as Record<PwaCacheCounterMetric, number>;
}

export function emptyQuota(): PwaCacheMetricsSnapshot["quota"] {
  return { lastEstimatedAt: null, quotaBytes: null, supported: null, usageBytes: null };
}

export function emptyWaitDurations(): PersistedMetrics["requestWait"] {
  return { averageDurationMs: 0, durationObservations: 0, maxDurationMs: 0, totalDurationMs: 0 };
}

export function browserStorage(): PwaCacheMetricsStorage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function positive(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

export function positiveInteger(value: unknown, fallback: number): number {
  const parsed = finiteInteger(value, fallback);
  return parsed > 0 ? parsed : fallback;
}

export function finiteInteger(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : fallback;
}

export function finiteTimestamp(value: number, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : fallback;
}

export function finiteBytes(value: number | null): number | null {
  return value === null ? null : finiteNumber(value);
}

function plainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function optionalFiniteNumber(value: unknown): number | null {
  return value === null ? null : finiteNumber(value);
}
