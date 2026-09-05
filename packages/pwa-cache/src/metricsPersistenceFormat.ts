import {
  PWA_CACHE_COUNTER_METRICS,
  PWA_CACHE_METRICS_SCHEMA,
  type PwaCacheCounterMetric,
  type PwaCacheMetricsSnapshot,
} from "./metricsTypes";

export type PersistedMetrics = Omit<PwaCacheMetricsSnapshot, "requestWait"> & {
  requestWait: Omit<PwaCacheMetricsSnapshot["requestWait"], "oldestPendingMs" | "pendingCount">;
};

export type PersistedMetricsShard = Omit<PersistedMetrics, "requestWait"> & {
  collectorId: string;
  requestWait: PersistedMetrics["requestWait"] & {
    oldestPendingStartedAt: number | null;
    pendingCount: number;
  };
  resetId: string;
};

const COLLECTOR_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/u;

export function parsePersistedMetrics(raw: string): PersistedMetrics | null {
  let value: Partial<PersistedMetrics>;
  try {
    value = JSON.parse(raw) as Partial<PersistedMetrics>;
  } catch {
    return null;
  }
  if (!value || value.schema !== PWA_CACHE_METRICS_SCHEMA || !plainObject(value.counters)
      || !plainObject(value.quota) || !plainObject(value.requestWait)) return null;
  const counters = emptyCounters();
  for (const name of PWA_CACHE_COUNTER_METRICS) {
    counters[name] = finiteInteger(value.counters[name], 0);
  }
  const windowStartedAt = finiteNumber(value.windowStartedAt);
  const updatedAt = finiteNumber(value.updatedAt);
  if (windowStartedAt === null || updatedAt === null) return null;
  const durationObservations = finiteInteger(value.requestWait.durationObservations, 0);
  const totalDurationMs = finiteInteger(value.requestWait.totalDurationMs, 0);
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
      averageDurationMs: durationObservations > 0 ? Math.round(totalDurationMs / durationObservations) : 0,
      durationObservations,
      maxDurationMs: finiteInteger(value.requestWait.maxDurationMs, 0),
      totalDurationMs,
    },
    updatedAt,
    windowStartedAt,
  };
}

export function parsePersistedMetricsShard(raw: string): PersistedMetricsShard | null {
  const persisted = parsePersistedMetrics(raw);
  if (!persisted) return null;
  let value: Record<string, unknown>;
  try {
    value = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
  const requestWait = plainObject(value.requestWait) ? value.requestWait : {};
  if (!validCollectorId(value.collectorId) || !validResetId(value.resetId)) return null;
  return {
    ...persisted,
    collectorId: value.collectorId,
    requestWait: {
      ...persisted.requestWait,
      oldestPendingStartedAt: optionalFiniteNumber(requestWait.oldestPendingStartedAt),
      pendingCount: finiteInteger(requestWait.pendingCount, 0),
    },
    resetId: value.resetId,
  };
}

export function persistedMetricsAreCurrent(
  value: PersistedMetrics,
  now: number,
  retentionMs: number,
): boolean {
  return value.windowStartedAt <= now
    && value.updatedAt >= value.windowStartedAt
    && value.updatedAt <= now
    && now - value.windowStartedAt <= retentionMs;
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

function validCollectorId(value: unknown): value is string {
  return typeof value === "string" && COLLECTOR_ID_PATTERN.test(value);
}

function validResetId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 192;
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
