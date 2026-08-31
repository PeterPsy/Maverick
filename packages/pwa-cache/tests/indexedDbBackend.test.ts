import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";
import {
  LOCAL_PERSISTENCE_POLICY_REVISION,
  PWA_CACHE_ENTRY_SCHEMA_VERSION,
  type CacheEntryMetadata,
} from "../src";
import { IndexedDbCacheBackend, cacheEntryKey } from "../src/testing";

function metadata(entityId = "one"): CacheEntryMetadata {
  const scope = {
    appId: "docs",
    policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
    resource: "records",
    userId: "user-a",
    workspaceId: "default",
  };
  return {
    ...scope,
    cachedAt: 1_000,
    dataClass: "public",
    entityId,
    expiresAt: 10_000,
    key: cacheEntryKey(scope, entityId),
    lastAccessedAt: 1_000,
    policy: "cache",
    provenance: "app_reference",
    revision: "r1",
    schemaVersion: PWA_CACHE_ENTRY_SCHEMA_VERSION,
    sizeBytes: 12,
    staleAt: 2_000,
  };
}

describe("IndexedDB cache schema", () => {
  it("migrates a v1 inline payload atomically into split metadata and payload stores", async () => {
    const factory = new IDBFactory();
    const name = "migration-success";
    await createV1Database(factory, name, { ...metadata(), payload: { value: "legacy" } });

    const backend = new IndexedDbCacheBackend({ databaseName: name, factory });
    await backend.initialize();

    expect(await backend.get(metadata().key)).toEqual({ metadata: metadata(), payload: { value: "legacy" } });
    expect((await openDatabase(factory, name)).version).toBe(2);
  });

  it("leaves the prior v1 store intact when the upgrade transaction is interrupted", async () => {
    const factory = new IDBFactory();
    const name = "migration-abort";
    const legacy = { ...metadata(), payload: { value: "legacy" } };
    await createV1Database(factory, name, legacy);
    const backend = new IndexedDbCacheBackend({
      databaseName: name,
      factory,
      migrationHook: (step) => {
        if (step === "split-payloads-v2") throw new Error("injected migration failure");
      },
    });

    await expect(backend.initialize()).rejects.toThrow(/injected migration failure/);
    const database = await openDatabase(factory, name);
    expect(database.version).toBe(1);
    const transaction = database.transaction("entries", "readonly");
    expect(await requestValue(transaction.objectStore("entries").get(metadata().key))).toEqual(legacy);
  });

  it("resumes a durable cleanup marker on the next bootstrap", async () => {
    const factory = new IDBFactory();
    const name = "cleanup-resume";
    const backend = new IndexedDbCacheBackend({ databaseName: name, factory });
    await backend.initialize();
    await backend.put({ metadata: metadata(), payload: { value: "cached" } });
    const database = await openDatabase(factory, name);
    const transaction = database.transaction("metadata", "readwrite");
    transaction.objectStore("metadata").put({
      createdAt: 1_000,
      filter: { userId: "user-a" },
      id: "cleanup:injected",
      kind: "cleanup",
    });
    await transactionDone(transaction);

    const resumed = new IndexedDbCacheBackend({ databaseName: name, factory });
    await resumed.initialize();
    expect(await resumed.list()).toEqual([]);
    expect(await resumed.pendingCleanupCount()).toBe(0);
  });

  it("keeps metadata-only touch operations from rewriting payload records", async () => {
    const factory = new IDBFactory();
    const name = "metadata-touch";
    const backend = new IndexedDbCacheBackend({ databaseName: name, factory });
    await backend.initialize();
    await backend.put({ metadata: metadata(), payload: { value: "cached" } });
    await backend.touch(metadata().key, { cachedAt: 2_000, staleAt: 4_000 });

    const entry = await backend.get<{ value: string }>(metadata().key);
    expect(entry?.metadata.cachedAt).toBe(2_000);
    expect(entry?.payload).toEqual({ value: "cached" });
  });
});

async function createV1Database(factory: IDBFactory, name: string, record: unknown): Promise<void> {
  const request = factory.open(name, 1);
  request.onupgradeneeded = () => request.result.createObjectStore("entries", { keyPath: "key" });
  const database = await requestValue(request);
  const transaction = database.transaction("entries", "readwrite");
  transaction.objectStore("entries").put(record);
  await transactionDone(transaction);
  database.close();
}

function openDatabase(factory: IDBFactory, name: string): Promise<IDBDatabase> {
  return requestValue(factory.open(name));
}

function requestValue<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}
