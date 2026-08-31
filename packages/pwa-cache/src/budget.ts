import type { CacheBackend, CacheEntryMetadata, CacheScope, CacheTelemetry } from "./types";

export type CacheBudgets = {
  globalBytes: number;
  maxAppBytes: number;
  maxScopeBytes: number;
};

export async function enforceCacheBudgets(
  backend: CacheBackend,
  scope: CacheScope,
  budgets: CacheBudgets,
  now: number,
  telemetry: CacheTelemetry,
): Promise<void> {
  const all = await backend.list();
  const expired = all.filter((entry) => entry.expiresAt <= now);
  await evict(backend, expired, telemetry, "expired");

  const remaining = all.filter((entry) => entry.expiresAt > now);
  await enforceLimit(
    backend,
    remaining.filter((entry) => sameResourceScope(entry, scope)),
    budgets.maxScopeBytes,
    telemetry,
    "resource-budget",
  );

  const afterResource = await backend.list();
  await enforceLimit(
    backend,
    afterResource.filter((entry) => sameAppScope(entry, scope)),
    budgets.maxAppBytes,
    telemetry,
    "app-budget",
  );

  await enforceLimit(backend, await backend.list(), budgets.globalBytes, telemetry, "origin-budget");
}

async function enforceLimit(
  backend: CacheBackend,
  entries: CacheEntryMetadata[],
  limit: number,
  telemetry: CacheTelemetry,
  reason: string,
): Promise<void> {
  let total = entries.reduce((sum, entry) => sum + entry.sizeBytes, 0);
  if (total <= limit) {
    return;
  }
  const oldestFirst = [...entries].sort((left, right) =>
    left.lastAccessedAt - right.lastAccessedAt || left.cachedAt - right.cachedAt || left.key.localeCompare(right.key),
  );
  const victims: CacheEntryMetadata[] = [];
  for (const entry of oldestFirst) {
    if (total <= limit) {
      break;
    }
    victims.push(entry);
    total -= entry.sizeBytes;
  }
  await evict(backend, victims, telemetry, reason);
}

async function evict(
  backend: CacheBackend,
  entries: CacheEntryMetadata[],
  telemetry: CacheTelemetry,
  reason: string,
): Promise<void> {
  let bytes = 0;
  let count = 0;
  for (const entry of entries) {
    if (await backend.delete(entry.key)) {
      bytes += entry.sizeBytes;
      count += 1;
    }
  }
  if (count > 0) {
    telemetry({ bytes, count, kind: "evict", reason });
  }
}

function sameAppScope(entry: CacheEntryMetadata, scope: CacheScope): boolean {
  return entry.userId === scope.userId
    && entry.workspaceId === scope.workspaceId
    && entry.appId === scope.appId;
}

function sameResourceScope(entry: CacheEntryMetadata, scope: CacheScope): boolean {
  return sameAppScope(entry, scope) && entry.resource === scope.resource;
}
