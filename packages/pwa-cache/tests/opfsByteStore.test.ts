import { afterEach, describe, expect, it, vi } from "vitest";
import { OpfsFileCacheByteStore, opaqueFileCachePath, validateOpaquePath } from "../src/testing";

afterEach(() => vi.unstubAllGlobals());

describe("OPFS file-cache adapter", () => {
  it("feature-detects OPFS and supports bounded chunk append without path traversal", async () => {
    const directory = new FakeDirectory();
    const root = {
      getDirectoryHandle: async () => directory,
    } as unknown as FileSystemDirectoryHandle;
    vi.stubGlobal("navigator", { storage: { getDirectory: async () => root } });
    const store = new OpfsFileCacheByteStore();
    const path = opaqueFileCachePath();

    expect(store.available()).toBe(true);
    expect(validateOpaquePath(path)).toBe(path);
    expect(() => validateOpaquePath("../leak.bin")).toThrow(/opaque flat names/i);
    await store.initialize();
    const first = await store.createWriter(path, 0);
    await first.write(new TextEncoder().encode("ab"));
    await first.close();
    const resumed = await store.createWriter(path, 2);
    await resumed.write(new TextEncoder().encode("c"));
    await resumed.close();

    expect(await (await store.read(path))?.text()).toBe("abc");
    expect(await store.list()).toEqual([path]);
    await store.delete(path);
    expect(await store.read(path)).toBeNull();
  });

  it("reports an unavailable adapter without touching persistent storage", () => {
    vi.stubGlobal("navigator", { storage: {} });
    expect(new OpfsFileCacheByteStore().available()).toBe(false);
  });
});

class FakeDirectory {
  readonly files = new Map<string, Uint8Array>();

  async getFileHandle(name: string, options?: { create?: boolean }) {
    if (!this.files.has(name) && !options?.create) throw domNotFound();
    if (!this.files.has(name)) this.files.set(name, new Uint8Array());
    return new FakeFileHandle(name, this.files) as unknown as FileSystemFileHandle;
  }

  async removeEntry(name: string) {
    if (!this.files.delete(name)) throw domNotFound();
  }

  async *entries(): AsyncIterableIterator<[string, FileSystemHandle]> {
    for (const name of this.files.keys()) {
      yield [name, { kind: "file", name } as FileSystemHandle];
    }
  }
}

class FakeFileHandle {
  constructor(private readonly name: string, private readonly files: Map<string, Uint8Array>) {}

  async getFile(): Promise<File> {
    const bytes = this.files.get(this.name);
    if (!bytes) throw domNotFound();
    return new File([bytes.slice().buffer], this.name);
  }

  async createWritable(options?: { keepExistingData?: boolean }) {
    let bytes = options?.keepExistingData ? this.files.get(this.name)?.slice() ?? new Uint8Array() : new Uint8Array();
    let position = 0;
    return {
      close: async () => { this.files.set(this.name, bytes.slice()); },
      seek: async (offset: number) => { position = offset; },
      truncate: async (size: number) => {
        const resized = new Uint8Array(size);
        resized.set(bytes.subarray(0, size));
        bytes = resized;
        position = Math.min(position, size);
      },
      write: async (chunk: Uint8Array) => {
        const next = new Uint8Array(Math.max(bytes.byteLength, position + chunk.byteLength));
        next.set(bytes);
        next.set(chunk, position);
        bytes = next;
        position += chunk.byteLength;
      },
    };
  }
}

function domNotFound(): DOMException {
  return new DOMException("missing", "NotFoundError");
}
