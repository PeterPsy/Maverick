import type { FileCacheByteStore, FileCacheByteWriter } from "./fileCacheTypes";

export const PWA_FILE_CACHE_OPFS_DIRECTORY = "maverick-pwa-file-cache-v1";
const OPAQUE_FILE_NAME = /^[a-z0-9][a-z0-9-]{7,95}\.bin$/u;

type StorageManagerWithOpfs = StorageManager & {
  getDirectory?: () => Promise<FileSystemDirectoryHandle>;
};
type IterableDirectoryHandle = FileSystemDirectoryHandle & {
  entries: () => AsyncIterableIterator<[string, FileSystemHandle]>;
};

export class OpfsFileCacheByteStore implements FileCacheByteStore {
  private directoryPromise: Promise<FileSystemDirectoryHandle> | null = null;

  available(): boolean {
    return typeof (globalThis.navigator?.storage as StorageManagerWithOpfs | undefined)?.getDirectory === "function";
  }

  async initialize(): Promise<void> {
    if (!this.available()) {
      throw new Error("OPFS is not available.");
    }
    await this.directory();
  }

  async createWriter(path: string, offset: number): Promise<FileCacheByteWriter> {
    validateOpaquePath(path);
    if (!Number.isSafeInteger(offset) || offset < 0) {
      throw new TypeError("OPFS write offset must be a non-negative integer.");
    }
    const handle = await (await this.directory()).getFileHandle(path, { create: true });
    const stream = await handle.createWritable({ keepExistingData: offset > 0 });
    if (offset === 0) {
      await stream.truncate(0);
    } else {
      await stream.seek(offset);
    }
    return {
      close: () => stream.close(),
      truncate: (size) => stream.truncate(size),
      write: (chunk) => stream.write(Uint8Array.from(chunk)),
    };
  }

  async delete(path: string): Promise<void> {
    validateOpaquePath(path);
    try {
      await (await this.directory()).removeEntry(path);
    } catch (error) {
      if (!isNotFoundError(error)) throw error;
    }
  }

  async list(): Promise<string[]> {
    const entries: string[] = [];
    const directory = await this.directory() as IterableDirectoryHandle;
    for await (const [name, handle] of directory.entries()) {
      if (handle.kind === "file" && OPAQUE_FILE_NAME.test(name)) {
        entries.push(name);
      }
    }
    return entries.sort();
  }

  async read(path: string): Promise<Blob | null> {
    validateOpaquePath(path);
    try {
      const handle = await (await this.directory()).getFileHandle(path);
      return await handle.getFile();
    } catch (error) {
      if (isNotFoundError(error)) return null;
      throw error;
    }
  }

  private directory(): Promise<FileSystemDirectoryHandle> {
    if (!this.directoryPromise) {
      this.directoryPromise = this.openDirectory();
    }
    return this.directoryPromise;
  }

  private async openDirectory(): Promise<FileSystemDirectoryHandle> {
    const storage = globalThis.navigator?.storage as StorageManagerWithOpfs | undefined;
    if (typeof storage?.getDirectory !== "function") {
      throw new Error("OPFS is not available.");
    }
    const root = await storage.getDirectory();
    return root.getDirectoryHandle(PWA_FILE_CACHE_OPFS_DIRECTORY, { create: true });
  }
}

export function opaqueFileCachePath(): string {
  const random = globalThis.crypto?.randomUUID?.().toLowerCase()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `cache-${random.replace(/[^a-z0-9-]/gu, "-")}.bin`;
}

export function validateOpaquePath(path: string): string {
  if (!OPAQUE_FILE_NAME.test(path)) {
    throw new TypeError("File-cache OPFS paths must be opaque flat names.");
  }
  return path;
}

function isNotFoundError(error: unknown): boolean {
  return Boolean(error) && typeof error === "object" && (error as { name?: unknown }).name === "NotFoundError";
}
