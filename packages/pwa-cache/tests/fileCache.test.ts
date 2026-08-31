import { describe, expect, it, vi } from "vitest";
import {
  BrowserFileCacheMaintenance,
  createPwaFileCacheHost,
  type FileCacheDescriptor,
  type StorageQuotaAdapter,
} from "../src";
import { MemoryFileCacheByteStore, MemoryFileCacheManifestStore, sha256Blob } from "../src/testing";

const quota: StorageQuotaAdapter = {
  canWrite: async () => true,
  estimate: async () => ({ quota: 1024 * 1024, supported: true, usage: 0 }),
};

function descriptor(bytes: Uint8Array, overrides: Partial<FileCacheDescriptor> = {}): FileCacheDescriptor {
  return {
    contentType: "text/plain",
    dataClass: "public",
    fileId: "file-one",
    provenance: "attachment",
    sizeBytes: bytes.byteLength,
    sourceVersion: "version-one",
    ...overrides,
  };
}

function cache(options: {
  bytes?: MemoryFileCacheByteStore;
  fetchImpl: typeof fetch;
  globalBudgetBytes?: number;
  manifest?: MemoryFileCacheManifestStore;
  maxScopeBytes?: number;
}) {
  const manifest = options.manifest ?? new MemoryFileCacheManifestStore();
  const bytes = options.bytes ?? new MemoryFileCacheByteStore();
  const instance = createPwaFileCacheHost({
    appId: "storage",
    userId: "user-a",
    workspaceId: "default",
  }).createCache({
    byteStore: bytes,
    enabled: true,
    fetchImpl: options.fetchImpl,
    globalBudgetBytes: options.globalBudgetBytes,
    manifestStore: manifest,
    maxScopeBytes: options.maxScopeBytes,
    quotaAdapter: quota,
  });
  return { bytes, cache: instance, manifest };
}

describe("transparent PWA file cache", () => {
  it("publishes verified streamed bytes and opens a subsequent request cache-first", async () => {
    const payload = new TextEncoder().encode("cached file");
    const expectedSha256 = await sha256Blob(new Blob([payload]));
    const fetchImpl = vi.fn(async () => response(payload, 200, { ETag: '"etag-one"' })) as unknown as typeof fetch;
    const runtime = cache({ fetchImpl });
    const request = {
      descriptor: descriptor(payload, { expectedSha256 }),
      url: "/api/apps/storage/media?stable_storage_file_id=file-one",
    };

    const first = await runtime.cache.open(request);
    expect(first.source).toBe("network");
    expect(await first.blob.text()).toBe("cached file");
    await first.cacheCompletion;
    expect(await runtime.manifest.list({ state: "ready" })).toHaveLength(1);

    const second = await runtime.cache.open(request);
    expect(second.source).toBe("cache");
    expect(await second.blob.text()).toBe("cached file");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("resumes an interrupted same-session stream with Range and strong If-Range", async () => {
    const complete = new TextEncoder().encode("abcdef");
    const expectedSha256 = await sha256Blob(new Blob([complete]));
    const calls: Array<{ range: string | null; ifRange: string | null }> = [];
    let attempt = 0;
    const fetchImpl = (async (_url: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      calls.push({ range: headers.get("Range"), ifRange: headers.get("If-Range") });
      attempt += 1;
      if (attempt === 1) {
        let sent = false;
        const stream = new ReadableStream<Uint8Array>({
          async pull(controller) {
            if (!sent) {
              sent = true;
              controller.enqueue(new TextEncoder().encode("abc"));
              return;
            }
            await new Promise((resolve) => setTimeout(resolve, 5));
            controller.error(new TypeError("connection reset"));
          },
        });
        return new Response(stream, { headers: { ETag: '"etag-one"' }, status: 200 });
      }
      return response(new TextEncoder().encode("def"), 206, {
        "Content-Range": "bytes 3-5/6",
        ETag: '"etag-one"',
      });
    }) as typeof fetch;
    const runtime = cache({ fetchImpl });
    const request = {
      descriptor: descriptor(complete, { expectedSha256 }),
      url: "/api/apps/storage/media?stable_storage_file_id=file-one",
    };

    await expect(runtime.cache.open(request)).rejects.toMatchObject({ name: "MaverickTransportError" });
    await until(() => [...runtime.manifest.records.values()].some((record) => record.writtenBytes === 3));
    expect([...runtime.bytes.files.values()].map((value) => value.byteLength)).toEqual([3]);
    const resumed = await runtime.cache.open(request);
    expect(await resumed.blob.text()).toBe("abcdef");
    await resumed.cacheCompletion;
    expect(calls).toEqual([
      { range: null, ifRange: null },
      { range: "bytes=3-", ifRange: '"etag-one"' },
    ]);
    expect((await runtime.manifest.list())[0]).toMatchObject({ state: "ready", writtenBytes: 6 });
  });

  it("returns a successful network body when OPFS writing fails", async () => {
    class FailingBytes extends MemoryFileCacheByteStore {
      override async createWriter(...args: Parameters<MemoryFileCacheByteStore["createWriter"]>) {
        const writer = await super.createWriter(...args);
        return { ...writer, write: async () => { throw new DOMException("quota", "QuotaExceededError"); } };
      }
    }
    const payload = new TextEncoder().encode("network survives");
    const runtime = cache({
      bytes: new FailingBytes(),
      fetchImpl: (async () => response(payload, 200, { ETag: '"etag-one"' })) as typeof fetch,
    });

    const opened = await runtime.cache.open({ descriptor: descriptor(payload), url: "/media" });
    expect(opened.source).toBe("network");
    expect(await opened.blob.text()).toBe("network survives");
    await opened.cacheCompletion;
    expect(await runtime.manifest.list()).toEqual([]);
    expect(await runtime.bytes.list()).toEqual([]);
  });

  it("does not publish a digest mismatch but keeps the network result usable", async () => {
    const payload = new TextEncoder().encode("actual bytes");
    const runtime = cache({
      fetchImpl: (async () => response(payload, 200, { ETag: '"etag-one"' })) as typeof fetch,
    });
    const opened = await runtime.cache.open({
      descriptor: descriptor(payload, { expectedSha256: "0".repeat(64) }),
      url: "/media",
    });

    expect(await opened.blob.text()).toBe("actual bytes");
    await opened.cacheCompletion;
    expect(await runtime.manifest.list()).toEqual([]);
    expect(await runtime.bytes.list()).toEqual([]);
  });

  it("keeps the prior ready version until the replacement is verified", async () => {
    class GatedManifest extends MemoryFileCacheManifestStore {
      release: (() => void) | null = null;

      override async put(record: Parameters<MemoryFileCacheManifestStore["put"]>[0]) {
        if (record.state === "ready" && record.sourceVersion === "version-two") {
          await new Promise<void>((resolve) => { this.release = resolve; });
        }
        return super.put(record);
      }
    }
    const firstBytes = new TextEncoder().encode("one!");
    const secondBytes = new TextEncoder().encode("two!");
    let payload = firstBytes;
    const manifest = new GatedManifest();
    const runtime = cache({
      fetchImpl: (async () => response(payload, 200, { ETag: payload === firstBytes ? '"one"' : '"two"' })) as typeof fetch,
      manifest,
    });
    const first = await runtime.cache.open({ descriptor: descriptor(firstBytes), url: "/media" });
    await first.cacheCompletion;
    const firstPath = (await runtime.manifest.list())[0].opfsPath;

    payload = secondBytes;
    const second = await runtime.cache.open({
      descriptor: descriptor(secondBytes, { sourceVersion: "version-two" }),
      url: "/media",
    });
    expect((await runtime.manifest.list()).some((record) => record.opfsPath === firstPath)).toBe(true);
    manifest.release?.();
    await second.cacheCompletion;
    expect(await runtime.manifest.list()).toHaveLength(1);
    expect((await runtime.manifest.list())[0]).toMatchObject({ sourceVersion: "version-two", state: "ready" });
    expect(runtime.bytes.files.has(firstPath)).toBe(false);
  });

  it("evicts least-recent files to enforce both scope and global budgets", async () => {
    let payload = new TextEncoder().encode("1111");
    const runtime = cache({
      fetchImpl: (async () => response(payload, 200, { ETag: `"${new TextDecoder().decode(payload)}"` })) as typeof fetch,
      globalBudgetBytes: 6,
      maxScopeBytes: 6,
    });
    const first = await runtime.cache.open({ descriptor: descriptor(payload), url: "/one" });
    await first.cacheCompletion;
    payload = new TextEncoder().encode("2222");
    const second = await runtime.cache.open({
      descriptor: descriptor(payload, { fileId: "file-two", sourceVersion: "version-two" }),
      url: "/two",
    });
    await second.cacheCompletion;

    expect(await runtime.manifest.list()).toHaveLength(1);
    expect((await runtime.manifest.list())[0].fileId).toBe("file-two");
  });

  it("falls back to the ordinary network path when OPFS is unavailable", async () => {
    const payload = new TextEncoder().encode("network only");
    const fetchImpl = vi.fn(async () => response(payload, 200, { ETag: '"etag"' })) as unknown as typeof fetch;
    const runtime = cache({ bytes: new MemoryFileCacheByteStore(false), fetchImpl });

    const opened = await runtime.cache.open({ descriptor: descriptor(payload), url: "/media" });
    expect(opened.source).toBe("network");
    expect(await opened.blob.text()).toBe("network only");
    expect(await runtime.manifest.list()).toEqual([]);
  });

  it("falls back to the ordinary network path when OPFS initialization is denied", async () => {
    class DeniedBytes extends MemoryFileCacheByteStore {
      override async initialize(): Promise<void> {
        throw new DOMException("denied", "NotAllowedError");
      }
    }
    const payload = new TextEncoder().encode("network only");
    const fetchImpl = vi.fn(async () => response(payload, 200, { ETag: '"etag"' })) as unknown as typeof fetch;
    const runtime = cache({ bytes: new DeniedBytes(), fetchImpl });

    const opened = await runtime.cache.open({ descriptor: descriptor(payload), url: "/media" });

    expect(opened.source).toBe("network");
    expect(await opened.blob.text()).toBe("network only");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("discards local setup failures instead of attempting a zero-byte resume", async () => {
    class InitiallyFailingBytes extends MemoryFileCacheByteStore {
      attempts = 0;

      override async createWriter(...args: Parameters<MemoryFileCacheByteStore["createWriter"]>) {
        this.attempts += 1;
        if (this.attempts === 1) throw new DOMException("quota", "QuotaExceededError");
        return super.createWriter(...args);
      }
    }
    const payload = new TextEncoder().encode("network survives");
    const ranges: Array<string | null> = [];
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      ranges.push(new Headers(init?.headers).get("Range"));
      return response(payload, 200, { ETag: '"etag"' });
    }) as unknown as typeof fetch;
    const runtime = cache({ bytes: new InitiallyFailingBytes(), fetchImpl });
    const request = { descriptor: descriptor(payload), url: "/media" };

    const first = await runtime.cache.open(request);
    await first.cacheCompletion;
    const second = await runtime.cache.open(request);
    await second.cacheCompletion;

    expect(ranges).toEqual([null, null]);
  });

  it("removes obsolete ready versions during maintenance recovery", async () => {
    const payload = new TextEncoder().encode("file");
    const runtime = cache({
      fetchImpl: (async () => response(payload, 200, { ETag: '"etag"' })) as typeof fetch,
    });
    const opened = await runtime.cache.open({ descriptor: descriptor(payload), url: "/media" });
    await opened.cacheCompletion;
    const old = (await runtime.manifest.list())[0];
    const current = {
      ...old,
      cachedAt: old.cachedAt + 1,
      key: "current-version-key",
      lastAccessedAt: old.lastAccessedAt + 1,
      opfsPath: "cache-current-version.bin",
      sourceVersion: "version-two",
    };
    runtime.bytes.files.set(current.opfsPath, payload);
    await runtime.manifest.put(current);

    await new BrowserFileCacheMaintenance(runtime.manifest, runtime.bytes).initialize();

    expect((await runtime.manifest.list()).map((record) => record.sourceVersion)).toEqual(["version-two"]);
    expect(await runtime.bytes.list()).toEqual(["cache-current-version.bin"]);
  });

  it("clears only the requested principal and its OPFS bytes", async () => {
    const payload = new TextEncoder().encode("file");
    const runtime = cache({
      fetchImpl: (async () => response(payload, 200, { ETag: '"etag"' })) as typeof fetch,
    });
    const opened = await runtime.cache.open({ descriptor: descriptor(payload), url: "/media" });
    await opened.cacheCompletion;
    const other = structuredClone((await runtime.manifest.list())[0]);
    other.key = "other-key";
    other.userId = "user-b";
    other.opfsPath = "cache-other.bin";
    runtime.bytes.files.set(other.opfsPath, payload);
    await runtime.manifest.put(other);

    const maintenance = new BrowserFileCacheMaintenance(runtime.manifest, runtime.bytes);
    await expect(maintenance.clear({ userId: "user-a" })).resolves.toMatchObject({ status: "complete", removed: 1 });
    expect((await runtime.manifest.list()).map((record) => record.userId)).toEqual(["user-b"]);
    expect(await runtime.bytes.list()).toEqual(["cache-other.bin"]);
  });
});

function response(bytes: Uint8Array, status: number, headers: Record<string, string>): Response {
  return new Response(bytes.slice().buffer, {
    headers: { "Content-Length": String(bytes.byteLength), "Content-Type": "text/plain", ...headers },
    status,
  });
}

async function until(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error("condition not reached");
}
