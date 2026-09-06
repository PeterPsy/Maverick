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

export function aggregateMetricsShards(
  shards: readonly PersistedMetricsShard[],
  now: number,
  activeWaits: readonly number[],
): PwaCacheMetricsSnapshot {
  const counters = emptyCounters();
  let durationObservations = 0;
  let maxDurationMs = 0;
  const oldestPendingStartedAt = activeWaits.length ? Math.min(...activeWaits) : null;
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
      pendingCount: activeWaits.length,
      totalDurationMs,
    },
    updatedAt: shards.length ? updatedAt : now,
    windowStartedAt,
  };
}

function saturatedAdd(left: number, right: number): number {
  return Math.min(Number.MAX_SAFE_INTEGER, left + right);
}
