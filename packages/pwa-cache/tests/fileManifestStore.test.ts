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
    cleanupEpoch: 0,
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
    writeGeneration: 1,
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

  it("rejects publication from a writer reserved before a completed cleanup epoch", async () => {
    const store = new IndexedDbFileCacheManifestStore({
      databaseName: "file-manifest-cleanup-epoch",
      factory: new IDBFactory(),
    });
    await store.initialize();
    const writing = record({
      etag: '"etag-one"',
      lastVerifiedAt: 0,
      sha256: "",
      state: "writing",
      writtenBytes: 0,
      writeGeneration: 0,
      writerSessionId: "writer-one",
    });
    const reserved = await store.reserveWriting(writing, 0);
    expect(reserved).not.toBeNull();
    const marker = await store.createCleanupMarker({ userId: "user-a" });
    await store.delete(reserved!.key);
    await store.deleteCleanupMarker(marker.id);

    const result = await store.publishReady({
      ...reserved!,
      lastVerifiedAt: 2,
      sha256: "a".repeat(64),
      state: "ready",
      writtenBytes: reserved!.sizeBytes,
    });

    expect(result).toEqual({ obsoleteRecords: [], published: false });
    expect(await store.list()).toEqual([]);
    expect(await store.getCleanupEpoch()).toBe(1);
  });

  it("publishes only the newest generation for one file identity", async () => {
    const store = new IndexedDbFileCacheManifestStore({
      databaseName: "file-manifest-source-generations",
      factory: new IDBFactory(),
    });
    await store.initialize();
    const baseWriting = record({
      etag: '"etag"',
      lastVerifiedAt: 0,
      sha256: "",
      state: "writing",
      writtenBytes: 0,
      writeGeneration: 0,
      writerSessionId: "writer-one",
    });
    const old = await store.reserveWriting(baseWriting, 0);
    const current = await store.reserveWriting({
      ...baseWriting,
      key: "key-two",
      opfsPath: "cache-two.bin",
      sourceVersion: "version-two",
      writerSessionId: "writer-two",
    }, 0);
    expect(old?.writeGeneration).toBe(1);
    expect(current?.writeGeneration).toBe(2);

    const currentResult = await store.publishReady({
      ...current!,
      lastVerifiedAt: 2,
      sha256: "b".repeat(64),
      state: "ready",
      writtenBytes: current!.sizeBytes,
    });
    const oldResult = await store.publishReady({
      ...old!,
      lastVerifiedAt: 3,
      sha256: "a".repeat(64),
      state: "ready",
      writtenBytes: old!.sizeBytes,
    });

    expect(currentResult.published).toBe(true);
    expect(currentResult.obsoleteRecords).toEqual([old]);
    expect(oldResult.published).toBe(false);
    expect((await store.list()).map((value) => value.sourceVersion)).toEqual(["version-two"]);
  });
});
