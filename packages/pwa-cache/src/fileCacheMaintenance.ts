import {
  markFileCacheCleanupPending,
  pendingFileCacheCleanupFilters,
  resolveFileCacheCleanup,
} from "./fileCleanupBarrier";
import { IndexedDbFileCacheManifestStore } from "./fileManifestStore";
import { OpfsFileCacheByteStore } from "./opfsByteStore";
import type {
  FileCacheByteStore,
  FileCacheDiagnostics,
  FileCacheFilter,
  FileCacheMaintenance,
  FileCacheManifestStore,
  FileCacheRecord,
} from "./fileCacheTypes";
import type { AccessLease, CacheCleanupResult, CachePrincipal } from "./types";

const WRITING_LEASE_GRACE_MS = 5 * 60_000;

export class BrowserFileCacheMaintenance implements FileCacheMaintenance {
  constructor(
    private readonly manifest: FileCacheManifestStore,
    private readonly bytes: FileCacheByteStore,
    private readonly now: () => number = Date.now,
  ) {}

  async initialize(): Promise<void> {
    await this.manifest.initialize();
    if (this.bytes.available()) await this.bytes.initialize();
    await this.resumeCleanups();
    await this.cleanupAbandonedWritesAndOrphans();
  }

  async clear(filter: FileCacheFilter = {}): Promise<CacheCleanupResult> {
    markFileCacheCleanupPending(filter);
    let markerId = "";
    try {
      await this.manifest.initialize();
      markerId = (await this.manifest.createCleanupMarker(filter)).id;
      const removed = await this.deleteRecords(filter);
      await this.manifest.deleteCleanupMarker(markerId);
      resolveFileCacheCleanup(filter);
      const pendingCleanupCount = await this.pendingCleanupCount();
      return {
        pendingCleanupCount,
        removed,
        status: pendingCleanupCount > 0 ? "pending" : "complete",
      };
    } catch {
      return {
        pendingCleanupCount: Math.max(1, await this.pendingCleanupCount().catch(() => 1)),
        removed: 0,
        status: "pending",
      };
    }
  }

  async diagnostics(): Promise<FileCacheDiagnostics> {
    try {
      await this.manifest.initialize();
      const records = (await this.manifest.list()).filter((record) => record.state === "ready");
      return {
        available: this.bytes.available(),
        bytes: records.reduce((total, record) => total + record.sizeBytes, 0),
        entryCount: records.length,
        pendingCleanupCount: await this.pendingCleanupCount(),
      };
    } catch {
      return {
        available: false,
        bytes: 0,
        entryCount: 0,
        pendingCleanupCount: Math.max(0, pendingFileCacheCleanupFilters().length),
      };
    }
  }

  async renewAccessLease(principal: CachePrincipal, lease: AccessLease): Promise<void> {
    await this.manifest.initialize();
    const records = await this.manifest.list(principal);
    await Promise.all(records
      .filter((record) => record.state === "ready" && record.dataClass !== "public")
      .map((record) => this.manifest.put({ ...record, accessLeaseExpiresAt: lease.expiresAt })));
  }

  private async resumeCleanups(): Promise<void> {
    const markers = await this.manifest.listCleanupMarkers();
    const pending = [...markers.map((marker) => marker.filter), ...pendingFileCacheCleanupFilters()];
    for (const filter of uniqueFilters(pending)) {
      await this.deleteRecords(filter);
      for (const marker of markers) {
        if (filterCovers(filter, marker.filter)) await this.manifest.deleteCleanupMarker(marker.id);
      }
      resolveFileCacheCleanup(filter);
    }
  }

  private async deleteRecords(filter: FileCacheFilter): Promise<number> {
    const records = await this.manifest.list(filter);
    if (records.length > 0 && !this.bytes.available()) {
      throw new Error("OPFS is unavailable while file-cache cleanup is pending.");
    }
    let removed = 0;
    for (const record of records) {
      await this.bytes.delete(record.opfsPath);
      if (await this.manifest.delete(record.key)) removed += 1;
    }
    return removed;
  }

  private async pendingCleanupCount(): Promise<number> {
    const markers = await this.manifest.listCleanupMarkers();
    return Math.max(markers.length, pendingFileCacheCleanupFilters().length);
  }

  private async cleanupAbandonedWritesAndOrphans(): Promise<void> {
    if (!this.bytes.available()) return;
    const records = await this.manifest.list();
    const now = this.now();
    const abandoned = records.filter((record) => record.state !== "ready" && writeLeaseExpired(record, now));
    for (const record of abandoned) {
      await this.bytes.delete(record.opfsPath);
      await this.manifest.delete(record.key);
    }
    const retained = (await this.manifest.list()).filter((record) => record.state === "ready" || !writeLeaseExpired(record, now));
    const referenced = new Set(retained.map((record) => record.opfsPath));
    for (const path of await this.bytes.list()) {
      if (!referenced.has(path)) await this.bytes.delete(path);
    }
  }
}

export function createBrowserFileCacheMaintenance(): FileCacheMaintenance {
  const bytes = new OpfsFileCacheByteStore();
  try {
    return new BrowserFileCacheMaintenance(
      new IndexedDbFileCacheManifestStore(),
      bytes,
    );
  } catch {
    return new UnavailableFileCacheMaintenance(bytes.available());
  }
}

class UnavailableFileCacheMaintenance implements FileCacheMaintenance {
  constructor(private readonly mayContainOpfsBytes = false) {}

  async initialize(): Promise<void> {}

  async clear(filter: FileCacheFilter = {}): Promise<CacheCleanupResult> {
    if (this.mayContainOpfsBytes || pendingFileCacheCleanupFilters().length > 0) {
      markFileCacheCleanupPending(filter);
    }
    return {
      pendingCleanupCount: pendingFileCacheCleanupFilters().length,
      removed: 0,
      status: pendingFileCacheCleanupFilters().length > 0 ? "pending" : "complete",
    };
  }

  async diagnostics(): Promise<FileCacheDiagnostics> {
    return {
      available: false,
      bytes: 0,
      entryCount: 0,
      pendingCleanupCount: pendingFileCacheCleanupFilters().length,
    };
  }

  async renewAccessLease(_principal: CachePrincipal, _lease: AccessLease): Promise<void> {}
}

function writeLeaseExpired(record: FileCacheRecord, now: number): boolean {
  return typeof record.writeLeaseExpiresAt !== "number"
    || !Number.isFinite(record.writeLeaseExpiresAt)
    || record.writeLeaseExpiresAt + WRITING_LEASE_GRACE_MS <= now;
}

function uniqueFilters(filters: FileCacheFilter[]): FileCacheFilter[] {
  const values = new Map<string, FileCacheFilter>();
  filters.forEach((filter) => values.set(JSON.stringify(filter), filter));
  return [...values.values()];
}

function filterCovers(cleared: FileCacheFilter, pending: FileCacheFilter): boolean {
  return Object.entries(cleared).every(([key, value]) => pending[key as keyof FileCacheFilter] === value);
}
