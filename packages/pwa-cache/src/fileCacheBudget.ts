import type {
  FileCacheDescriptor,
  FileCacheManifestStore,
  FileCacheRecord,
  FileCacheTelemetryEvent,
} from "./fileCacheTypes";
import type { CachePrincipal } from "./types";

export async function enforceFileCacheBudget(options: {
  deleteRecord: (record: FileCacheRecord) => Promise<void>;
  descriptor: FileCacheDescriptor;
  globalBudgetBytes: number;
  manifest: FileCacheManifestStore;
  maxScopeBytes: number;
  principal: CachePrincipal;
  targetKey: string;
  telemetry: (event: FileCacheTelemetryEvent) => void;
}): Promise<boolean> {
  const records = await options.manifest.list();
  const protectedKeys = new Set(records
    .filter((record) => sameFile(record, options.principal, options.descriptor.fileId))
    .map((record) => record.key));
  protectedKeys.add(options.targetKey);
  let globalBytes = records.reduce((total, record) => total + recordBytes(record), 0);
  let scopeBytes = records
    .filter((record) => samePrincipal(record, options.principal))
    .reduce((total, record) => total + recordBytes(record), 0);
  const existing = records.find((record) => record.key === options.targetKey);
  const incoming = Math.max(0, options.descriptor.sizeBytes - (existing ? recordBytes(existing) : 0));
  globalBytes += incoming;
  scopeBytes += incoming;
  const victims = records
    .filter((record) => record.state === "ready" && !protectedKeys.has(record.key))
    .sort((left, right) => left.lastAccessedAt - right.lastAccessedAt
      || left.cachedAt - right.cachedAt
      || left.key.localeCompare(right.key));
  for (const victim of victims) {
    if (globalBytes <= options.globalBudgetBytes && scopeBytes <= options.maxScopeBytes) break;
    const size = recordBytes(victim);
    await options.deleteRecord(victim);
    globalBytes -= size;
    if (samePrincipal(victim, options.principal)) scopeBytes -= size;
    options.telemetry({ bytes: size, count: 1, kind: "evict", reason: "budget" });
  }
  return globalBytes <= options.globalBudgetBytes && scopeBytes <= options.maxScopeBytes;
}

function recordBytes(record: FileCacheRecord): number {
  // A writing record is a durable reservation for its complete declared size.
  // Counting only bytes already streamed makes concurrent budget checks race.
  return record.state === "ready" || record.state === "writing" ? record.sizeBytes : record.writtenBytes;
}

function samePrincipal(record: FileCacheRecord, principal: CachePrincipal): boolean {
  return record.userId === principal.userId
    && record.workspaceId === principal.workspaceId
    && record.appId === principal.appId;
}

function sameFile(record: FileCacheRecord, principal: CachePrincipal, fileId: string): boolean {
  return samePrincipal(record, principal) && record.fileId === fileId;
}
