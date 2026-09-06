import type { PwaCacheMetricsStorage } from "./metricsTypes";
import {
  parsePersistedMetrics,
  parsePersistedMetricsShard,
  persistedMetricsAreCurrent,
  type PersistedMetricsShard,
} from "./metricsPersistenceFormat";

export {
  emptyCounters,
  emptyQuota,
  emptyWaitDurations,
  finiteBytes,
  finiteInteger,
  finiteTimestamp,
  positive,
  positiveInteger,
  type PersistedMetrics,
  type PersistedMetricsShard,
} from "./metricsPersistenceFormat";

const RESET_SCHEMA = "maverick.pwa-cache-metrics-reset.v1";
const INITIAL_RESET_ID = "initial";
const COLLECTOR_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/u;
const PRUNE_BATCH_SIZE = 64;
const PRUNE_INTERVAL_MS = 60_000;

type MetricsResetMarker = {
  resetAt: number;
  resetId: string;
  schema: typeof RESET_SCHEMA;
};

export class MetricsShardPersistence {
  readonly collectorId: string;
  private readonly resetKey: string;
  private readonly storage: PwaCacheMetricsStorage;
  private readonly storageKey: string;
  private readonly writerPrefix: string;
  private pruneCursor = 0;
  private lastPrunedAt: number | null = null;

  constructor(storage: PwaCacheMetricsStorage, storageKey: string, collectorId?: string) {
    this.storage = storage;
    this.storageKey = storageKey;
    this.collectorId = normalizeCollectorId(collectorId);
    this.resetKey = `${storageKey}:reset`;
    this.writerPrefix = `${storageKey}:writer:`;
  }

  currentReset(): MetricsResetMarker {
    return this.readResetMarker()
      ?? { resetAt: 0, resetId: INITIAL_RESET_ID, schema: RESET_SCHEMA };
  }

  loadOwn(now: number, retentionMs: number, resetId: string): PersistedMetricsShard | null {
    const writerKey = this.writerKey(resetId);
    try {
      const raw = this.storage.getItem(writerKey);
      const shard = raw ? parsePersistedMetricsShard(raw) : null;
      if (shard && shard.collectorId === this.collectorId && shard.resetId === resetId
          && persistedMetricsAreCurrent(shard, now, retentionMs)) {
        return shard;
      }
      if (raw) this.storage.removeItem(writerKey);
    } catch {
      // A denied or corrupt diagnostics store never affects cache behavior.
    }
    return null;
  }

  readPeers(now: number, retentionMs: number, resetId: string): PersistedMetricsShard[] {
    this.prune(now, retentionMs);
    const peers: PersistedMetricsShard[] = [];
    const ownWriterKey = this.writerKey(resetId);
    try {
      for (const key of this.keys()) {
        if (!key.startsWith(this.writerPrefix) || key === ownWriterKey) continue;
        const raw = this.storage.getItem(key);
        const shard = raw ? parsePersistedMetricsShard(raw) : null;
        if (!shard || shard.resetId !== resetId || !persistedMetricsAreCurrent(shard, now, retentionMs)) {
          continue;
        }
        peers.push(shard);
      }
      if (resetId === INITIAL_RESET_ID) this.readLegacySnapshot(peers, now, retentionMs);
    } catch {
      // Return every shard read before storage became unavailable.
    }
    return peers;
  }

  persist(shard: PersistedMetricsShard, retentionMs: number): void {
    this.prune(shard.updatedAt, retentionMs);
    try {
      this.storage.setItem(this.writerKey(shard.resetId), JSON.stringify(shard));
    } catch {
      // Metrics are best-effort and never participate in the cache path.
    }
  }

  prune(now: number, retentionMs: number): void {
    if (this.lastPrunedAt !== null && now >= this.lastPrunedAt
        && now - this.lastPrunedAt < PRUNE_INTERVAL_MS) return;
    this.lastPrunedAt = now;
    try {
      const length = this.storage.length;
      if (this.pruneCursor >= length) this.pruneCursor = 0;
      const end = Math.min(length, this.pruneCursor + PRUNE_BATCH_SIZE);
      const keys: string[] = [];
      for (let index = this.pruneCursor; index < end; index += 1) {
        const key = this.storage.key(index);
        if (key && (key.startsWith(this.writerPrefix) || key === this.storageKey)) keys.push(key);
      }
      // Capture keys before observing the reset marker, as in explicit reset.
      // Generation-qualified keys protect writes from any subsequent reset.
      const resetRaw = this.storage.getItem(this.resetKey);
      const marker = resetRaw ? parseResetMarker(resetRaw) : null;
      // A denied/corrupt marker is not evidence that all other generations
      // are obsolete. Leave their history intact until a readable decision.
      if (resetRaw && !marker) return;
      const resetId = marker?.resetId ?? INITIAL_RESET_ID;
      let removed = 0;
      for (const key of keys) {
        const raw = this.storage.getItem(key);
        if (!raw) continue;
        const shard = key === this.storageKey ? parsePersistedMetrics(raw) : parsePersistedMetricsShard(raw);
        const generation = shard && "resetId" in shard ? shard.resetId : INITIAL_RESET_ID;
        if (shard && generation === resetId && persistedMetricsAreCurrent(shard, now, retentionMs)) continue;
        // A live writer may have refreshed a captured shard during inspection.
        if (this.storage.getItem(key) !== raw) continue;
        this.storage.removeItem(key);
        removed += 1;
      }
      this.pruneCursor = Math.max(0, end - removed);
    } catch {
      // Quota/denied storage must never interrupt cache reads or telemetry.
    }
  }

  removeOwn(resetId: string): void {
    try {
      this.storage.removeItem(this.writerKey(resetId));
    } catch {
      // Retention is still enforced in RAM when storage is denied.
    }
  }

  reset(now: number): MetricsResetMarker | null {
    const marker: MetricsResetMarker = {
      resetAt: now,
      resetId: `reset:${opaqueId()}`,
      schema: RESET_SCHEMA,
    };
    try {
      // The generation marker is the linearization point. Readers ignore any
      // prior generation even if a stale writer publishes after this write.
      this.storage.setItem(this.resetKey, JSON.stringify(marker));
    } catch {
      return null;
    }

    let keys: string[] = [];
    try {
      keys = this.keys();
    } catch {
      // A denied enumeration still leaves old generations logically hidden.
    }
    const winner = this.readResetMarker();
    if (!winner || winner.resetId !== marker.resetId) {
      return winner;
    }
    try {
      for (const key of keys) {
        if (key === this.storageKey) {
          this.storage.removeItem(key);
          continue;
        }
        if (!key.startsWith(this.writerPrefix)) continue;
        const raw = this.storage.getItem(key);
        const shard = raw ? parsePersistedMetricsShard(raw) : null;
        // A peer can observe the marker and publish a new-generation event
        // while cleanup runs. Preserve that causally newer write.
        if (!shard || shard.resetId !== winner.resetId) this.storage.removeItem(key);
      }
    } catch {
      // Prior-generation shards remain invisible even if pruning is denied.
    }
    // Another reset can win while cleanup is in progress. Generation-qualified
    // writer keys make the captured cleanup set safe, and the final reread makes
    // the caller commit its empty local shard into the actual winning window.
    return this.readResetMarker() ?? winner;
  }

  private readResetMarker(): MetricsResetMarker | null {
    try {
      const raw = this.storage.getItem(this.resetKey);
      return raw ? parseResetMarker(raw) : null;
    } catch {
      // Denied diagnostics storage behaves like an empty best-effort store.
      return null;
    }
  }

  private writerKey(resetId: string): string {
    return `${this.writerPrefix}${this.collectorId}:${resetId}`;
  }

  private keys(): string[] {
    const keys: string[] = [];
    const length = this.storage.length;
    for (let index = 0; index < length; index += 1) {
      const key = this.storage.key(index);
      if (key !== null) keys.push(key);
    }
    return keys;
  }

  private readLegacySnapshot(
    peers: PersistedMetricsShard[],
    now: number,
    retentionMs: number,
  ): void {
    const raw = this.storage.getItem(this.storageKey);
    const legacy = raw ? parsePersistedMetrics(raw) : null;
    if (legacy && persistedMetricsAreCurrent(legacy, now, retentionMs)) {
      peers.push({
        ...legacy,
        collectorId: "legacy",
        resetId: INITIAL_RESET_ID,
      });
    } else if (raw) {
      this.storage.removeItem(this.storageKey);
    }
  }
}

export function browserStorage(): PwaCacheMetricsStorage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

function parseResetMarker(raw: string): MetricsResetMarker | null {
  try {
    const value = JSON.parse(raw) as Partial<MetricsResetMarker>;
    return value.schema === RESET_SCHEMA && validResetId(value.resetId) && validTimestamp(value.resetAt)
      ? { resetAt: value.resetAt, resetId: value.resetId, schema: RESET_SCHEMA }
      : null;
  } catch {
    return null;
  }
}

function normalizeCollectorId(value: string | undefined): string {
  const candidate = value?.trim() || `collector:${opaqueId()}`;
  if (!validCollectorId(candidate)) {
    throw new TypeError("PWA metrics collector id must be an opaque bounded token.");
  }
  return candidate;
}

function opaqueId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function validCollectorId(value: unknown): value is string {
  return typeof value === "string" && COLLECTOR_ID_PATTERN.test(value);
}

function validResetId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 192;
}

function validTimestamp(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}
