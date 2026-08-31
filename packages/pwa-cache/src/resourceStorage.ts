import type {
  CacheBackend,
  CacheFilter,
  CacheScope,
  CacheTelemetry,
  LocalPersistencePolicy,
} from "./types";

export async function initializeResourceBackends(options: {
  memoryBackend: CacheBackend;
  persistencePolicy: LocalPersistencePolicy;
  persistentBackend: CacheBackend;
  scope: CacheScope;
  telemetry: CacheTelemetry;
}): Promise<void> {
  const { memoryBackend, persistencePolicy, persistentBackend, scope, telemetry } = options;
  await Promise.all([persistentBackend.initialize(), memoryBackend.initialize()]);
  const resourceFilter = {
    userId: scope.userId,
    workspaceId: scope.workspaceId,
    appId: scope.appId,
    resource: scope.resource,
  };
  await clearResourceBackend(
    persistentBackend,
    persistencePolicy === "cache"
      ? { ...resourceFilter, excludePolicyRevision: scope.policyRevision }
      : resourceFilter,
    telemetry,
    true,
  );
  await clearResourceBackend(
    memoryBackend,
    persistencePolicy === "deny"
      ? resourceFilter
      : { ...resourceFilter, excludePolicyRevision: scope.policyRevision },
    telemetry,
  );
}

export async function clearResourceBackend(
  backend: CacheBackend,
  filter: CacheFilter,
  telemetry: CacheTelemetry,
  durable = false,
): Promise<number> {
  try {
    return await backend.clear(filter, durable ? { durable: true } : undefined);
  } catch (error) {
    telemetry({ kind: "error", reason: error instanceof Error ? error.name : "unknown" });
    return 0;
  }
}
