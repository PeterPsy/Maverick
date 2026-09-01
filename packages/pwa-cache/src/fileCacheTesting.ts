import { fileCacheFilterMatches } from "./fileManifestStore";
import type {
  FileCacheByteStore,
  FileCacheByteWriter,
  FileCacheCleanupMarker,
  FileCacheFilter,
  FileCacheManifestStore,
  FileCachePublishResult,
  FileCacheRecord,
} from "./fileCacheTypes";

export class MemoryFileCacheManifestStore implements FileCacheManifestStore {
  readonly records = new Map<string, FileCacheRecord>();
  readonly markers = new Map<string, FileCacheCleanupMarker>();
  private cleanupEpoch = 0;
  private sequence = 0;
  private writeGeneration = 0;

  async initialize(): Promise<void> {}

  async get(key: string): Promise<FileCacheRecord | null> {
    const value = this.records.get(key);
    return value ? structuredClone(value) : null;
  }

  async put(record: FileCacheRecord): Promise<void> {
    this.records.set(record.key, structuredClone(record));
    if (Number.isSafeInteger(record.writeGeneration) && record.writeGeneration > this.writeGeneration) {
      this.writeGeneration = record.writeGeneration;
    }
  }

  async getCleanupEpoch(): Promise<number> {
    return this.cleanupEpoch;
  }

  async reserveWriting(record: FileCacheRecord, expectedCleanupEpoch: number): Promise<FileCacheRecord | null> {
    const current = this.records.get(record.key);
    if (this.cleanupEpoch !== expectedCleanupEpoch
        || this.cleanupBlocks(record)
        || (current && !sameWritingReservation(current, record))) return null;
    if (current) return structuredClone(current);
    this.writeGeneration += 1;
    const reserved = {
      ...structuredClone(record),
      cleanupEpoch: this.cleanupEpoch,
      writeGeneration: this.writeGeneration,
    };
    this.records.set(reserved.key, reserved);
    return structuredClone(reserved);
  }

  async updateWriting(record: FileCacheRecord): Promise<boolean> {
    return this.updateRecord(record, "writing");
  }

  async updateReady(record: FileCacheRecord): Promise<boolean> {
    return this.updateRecord(record, "ready");
  }

  async deleteWriting(record: FileCacheRecord): Promise<boolean> {
    const current = this.records.get(record.key);
    if (current?.state !== "writing" || !sameRecordGeneration(current, record)) return false;
    return this.records.delete(record.key);
  }

  async publishReady(record: FileCacheRecord): Promise<FileCachePublishResult> {
    const current = this.records.get(record.key);
    const identityRecords = [...this.records.values()].filter((candidate) => sameFileIdentity(candidate, record));
    if (this.cleanupEpoch !== record.cleanupEpoch
        || this.cleanupBlocks(record)
        || current?.state !== "writing"
        || !sameRecordGeneration(current, record)
        || identityRecords.some((candidate) => candidate.writeGeneration > record.writeGeneration)) {
      return { obsoleteRecords: [], published: false };
    }
    const obsoleteRecords = identityRecords.filter((candidate) => candidate.key !== record.key);
    this.records.set(record.key, structuredClone(record));
    obsoleteRecords.forEach((candidate) => this.records.delete(candidate.key));
    return { obsoleteRecords: structuredClone(obsoleteRecords), published: true };
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
    this.cleanupEpoch += 1;
    const marker: FileCacheCleanupMarker = {
      cleanupEpoch: this.cleanupEpoch,
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

  private cleanupBlocks(record: FileCacheRecord): boolean {
    return [...this.markers.values()].some((marker) => fileCacheFilterMatches(record, marker.filter));
  }

  private async updateRecord(record: FileCacheRecord, state: "ready" | "writing"): Promise<boolean> {
    const current = this.records.get(record.key);
    if ((state === "writing" && this.cleanupEpoch !== record.cleanupEpoch)
        || this.cleanupBlocks(record)
        || current?.state !== state
        || !sameRecordGeneration(current, record)) return false;
    this.records.set(record.key, structuredClone(record));
    return true;
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

function sameWritingReservation(left: FileCacheRecord, right: FileCacheRecord): boolean {
  return left.state === "writing"
    && right.state === "writing"
    && left.writerSessionId === right.writerSessionId
    && left.opfsPath === right.opfsPath;
}

function sameRecordGeneration(left: FileCacheRecord, right: FileCacheRecord): boolean {
  return left.key === right.key
    && left.cleanupEpoch === right.cleanupEpoch
    && left.writeGeneration === right.writeGeneration
    && left.writerSessionId === right.writerSessionId
    && left.opfsPath === right.opfsPath;
}

function sameFileIdentity(left: FileCacheRecord, right: FileCacheRecord): boolean {
  return left.userId === right.userId
    && left.workspaceId === right.workspaceId
    && left.appId === right.appId
    && left.fileId === right.fileId;
}
