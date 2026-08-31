import { fileCacheFilterMatches } from "./fileManifestStore";
import type {
  FileCacheByteStore,
  FileCacheByteWriter,
  FileCacheCleanupMarker,
  FileCacheFilter,
  FileCacheManifestStore,
  FileCacheRecord,
} from "./fileCacheTypes";

export class MemoryFileCacheManifestStore implements FileCacheManifestStore {
  readonly records = new Map<string, FileCacheRecord>();
  readonly markers = new Map<string, FileCacheCleanupMarker>();
  private sequence = 0;

  async initialize(): Promise<void> {}

  async get(key: string): Promise<FileCacheRecord | null> {
    const value = this.records.get(key);
    return value ? structuredClone(value) : null;
  }

  async put(record: FileCacheRecord): Promise<void> {
    this.records.set(record.key, structuredClone(record));
  }

  async delete(key: string): Promise<boolean> {
    return this.records.delete(key);
  }

  async list(filter: FileCacheFilter = {}): Promise<FileCacheRecord[]> {
    return Array.from(this.records.values())
      .filter((record) => fileCacheFilterMatches(record, filter))
      .map((record) => structuredClone(record));
  }

  async createCleanupMarker(filter: FileCacheFilter): Promise<FileCacheCleanupMarker> {
    this.sequence += 1;
    const marker: FileCacheCleanupMarker = {
      createdAt: Date.now(),
      filter: structuredClone(filter),
      id: `marker-${this.sequence}`,
      kind: "file-cache-cleanup",
    };
    this.markers.set(marker.id, marker);
    return structuredClone(marker);
  }

  async deleteCleanupMarker(id: string): Promise<void> {
    this.markers.delete(id);
  }

  async listCleanupMarkers(): Promise<FileCacheCleanupMarker[]> {
    return Array.from(this.markers.values(), (marker) => structuredClone(marker));
  }
}

export class MemoryFileCacheByteStore implements FileCacheByteStore {
  readonly files = new Map<string, Uint8Array>();

  constructor(private readonly supported = true) {}

  available(): boolean {
    return this.supported;
  }

  async initialize(): Promise<void> {
    if (!this.supported) throw new Error("Byte store unavailable.");
  }

  async createWriter(path: string, offset: number): Promise<FileCacheByteWriter> {
    if (!this.supported) throw new Error("Byte store unavailable.");
    let bytes = this.files.get(path)?.slice() ?? new Uint8Array();
    let position = offset;
    if (offset === 0) bytes = new Uint8Array();
    if (offset > bytes.byteLength) throw new Error("Write offset exceeds the stored file.");
    return {
      close: async () => {
        this.files.set(path, bytes.slice());
      },
      truncate: async (size) => {
        const next = new Uint8Array(size);
        next.set(bytes.subarray(0, size));
        bytes = next;
        position = Math.min(position, size);
        this.files.set(path, bytes.slice());
      },
      write: async (chunk) => {
        const required = position + chunk.byteLength;
        if (required > bytes.byteLength) {
          const expanded = new Uint8Array(required);
          expanded.set(bytes);
          bytes = expanded;
        }
        bytes.set(chunk, position);
        position = required;
        this.files.set(path, bytes.slice());
      },
    };
  }

  async delete(path: string): Promise<void> {
    this.files.delete(path);
  }

  async list(): Promise<string[]> {
    return [...this.files.keys()].sort();
  }

  async read(path: string): Promise<Blob | null> {
    const value = this.files.get(path);
    return value ? new Blob([value.slice().buffer]) : null;
  }
}
