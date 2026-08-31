import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";
import {
  PWA_FILE_CACHE_POLICY_REVISION,
  PWA_FILE_CACHE_SCHEMA_VERSION,
  type FileCacheRecord,
} from "../src";
import { IndexedDbFileCacheManifestStore } from "../src/testing";

function record(overrides: Partial<FileCacheRecord> = {}): FileCacheRecord {
  return {
    appId: "storage",
    cachedAt: 1,
    contentType: "text/plain",
    dataClass: "public",
    etag: '"etag-one"',
    fileId: "file-one",
    key: "key-one",
    lastAccessedAt: 1,
    lastVerifiedAt: 1,
    opfsPath: "cache-one.bin",
    policyRevision: PWA_FILE_CACHE_POLICY_REVISION,
    provenance: "attachment",
    schemaVersion: PWA_FILE_CACHE_SCHEMA_VERSION,
    sha256: "a".repeat(64),
    sizeBytes: 4,
    sourceVersion: "version-one",
    state: "ready",
    userId: "user-a",
    workspaceId: "default",
    writtenBytes: 4,
    ...overrides,
  };
}

describe("IndexedDB file-cache manifest", () => {
  it("persists scoped records and filters identities without exposing OPFS paths as keys", async () => {
    const store = new IndexedDbFileCacheManifestStore({
      databaseName: "file-manifest-scopes",
      factory: new IDBFactory(),
    });
    await store.initialize();
    await store.put(record());
    await store.put(record({ key: "key-two", userId: "user-b", opfsPath: "cache-two.bin" }));

    expect(await store.get("key-one")).toEqual(record());
    expect(await store.list({ userId: "user-a", workspaceId: "default" })).toEqual([record()]);
    expect(await store.list({ userId: "missing" })).toEqual([]);
  });

  it("keeps cleanup markers independent from file records", async () => {
    const store = new IndexedDbFileCacheManifestStore({
      databaseName: "file-manifest-cleanup",
      factory: new IDBFactory(),
      now: () => 42,
    });
    await store.initialize();
    await store.put(record());
    const marker = await store.createCleanupMarker({ userId: "user-a" });

    expect(await store.listCleanupMarkers()).toEqual([{ ...marker, createdAt: 42 }]);
    expect(await store.get("key-one")).toEqual(record());
    await store.deleteCleanupMarker(marker.id);
    expect(await store.listCleanupMarkers()).toEqual([]);
  });
});
