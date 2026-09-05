import { ResilientCacheBackend } from "./resilientBackend";
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
  if (persistencePolicy === "cache") {
    await clearResourceBackend(
      persistentBackend,
      { ...resourceFilter, excludePolicyRevision: scope.policyRevision },
      telemetry,
      true,
      true,
    );
    await clearResourceBackend(
      persistentBackend,
      {
        ...resourceFilter,
        policyRevision: scope.policyRevision,
        excludeSchemaRevision: scope.schemaRevision,
      },
      telemetry,
      true,
      true,
    );
  } else {
    await clearResourceBackend(persistentBackend, resourceFilter, telemetry, true, true);
  }
  if (persistencePolicy === "deny") {
    await clearResourceBackend(memoryBackend, resourceFilter, telemetry);
  } else {
    await clearResourceBackend(
      memoryBackend,
      { ...resourceFilter, excludePolicyRevision: scope.policyRevision },
      telemetry,
    );
    await clearResourceBackend(
      memoryBackend,
      {
        ...resourceFilter,
        policyRevision: scope.policyRevision,
        excludeSchemaRevision: scope.schemaRevision,
      },
      telemetry,
    );
  }
}

export async function clearResourceBackend(
  backend: CacheBackend,
  filter: CacheFilter,
  telemetry: CacheTelemetry,
  durable = false,
  maintenance = false,
): Promise<number> {
  try {
    const options = { durable };
    return maintenance && backend instanceof ResilientCacheBackend
      ? await backend.clearForMaintenance(filter, options)
      : await backend.clear(filter, options);
  } catch (error) {
    telemetry({ kind: "error", reason: error instanceof Error ? error.name : "unknown" });
    if (durable) {
      throw error;
    }
    return 0;
  }
}
