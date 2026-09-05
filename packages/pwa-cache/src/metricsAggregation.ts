import {
  PWA_CACHE_COUNTER_METRICS,
  PWA_CACHE_METRICS_SCHEMA,
  type PwaCacheMetricsSnapshot,
} from "./metricsTypes";
import {
  emptyCounters,
  emptyQuota,
  type PersistedMetricsShard,
} from "./metricsPersistence";

const MAX_PENDING_AGE_MS = 24 * 60 * 60 * 1_000;

export function aggregateMetricsShards(
  shards: readonly PersistedMetricsShard[],
  now: number,
): PwaCacheMetricsSnapshot {
  const counters = emptyCounters();
  let durationObservations = 0;
  let maxDurationMs = 0;
  let oldestPendingStartedAt: number | null = null;
  let pendingCount = 0;
  let quota = emptyQuota();
  let quotaUpdatedAt = -1;
  let totalDurationMs = 0;
  let updatedAt = 0;
  let windowStartedAt = now;

  for (const shard of shards) {
    updatedAt = Math.max(updatedAt, shard.updatedAt);
    windowStartedAt = Math.min(windowStartedAt, shard.windowStartedAt);
    for (const metric of PWA_CACHE_COUNTER_METRICS) {
      counters[metric] = saturatedAdd(counters[metric], shard.counters[metric]);
    }
    durationObservations = saturatedAdd(durationObservations, shard.requestWait.durationObservations);
    totalDurationMs = saturatedAdd(totalDurationMs, shard.requestWait.totalDurationMs);
    maxDurationMs = Math.max(maxDurationMs, shard.requestWait.maxDurationMs);

    const pendingStartedAt = shard.requestWait.oldestPendingStartedAt;
    if (pendingStartedAt !== null && pendingStartedAt <= now
        && now - pendingStartedAt <= MAX_PENDING_AGE_MS) {
      pendingCount = saturatedAdd(pendingCount, shard.requestWait.pendingCount);
      oldestPendingStartedAt = oldestPendingStartedAt === null
        ? pendingStartedAt
        : Math.min(oldestPendingStartedAt, pendingStartedAt);
    }

    const estimatedAt = shard.quota.lastEstimatedAt;
    if (estimatedAt !== null && estimatedAt >= quotaUpdatedAt) {
      quota = { ...shard.quota };
      quotaUpdatedAt = estimatedAt;
    }
  }

  return {
    schema: PWA_CACHE_METRICS_SCHEMA,
    counters,
    quota,
    requestWait: {
      averageDurationMs: durationObservations > 0 ? Math.round(totalDurationMs / durationObservations) : 0,
      durationObservations,
      maxDurationMs,
      oldestPendingMs: oldestPendingStartedAt === null ? null : Math.max(0, now - oldestPendingStartedAt),
      pendingCount,
      totalDurationMs,
    },
    updatedAt: shards.length ? updatedAt : now,
    windowStartedAt,
  };
}

function saturatedAdd(left: number, right: number): number {
  return Math.min(Number.MAX_SAFE_INTEGER, left + right);
}
