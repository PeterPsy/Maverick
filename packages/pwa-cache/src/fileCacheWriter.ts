import { isAbortError, transportError } from "./fileCacheNetwork";
import {
  PWA_FILE_CACHE_POLICY_REVISION,
  PWA_FILE_CACHE_SCHEMA_VERSION,
  type FileCacheByteStore,
  type FileCacheDescriptor,
  type FileCacheManifestStore,
  type FileCacheRecord,
  type FileCacheTelemetryEvent,
} from "./fileCacheTypes";
import { opaqueFileCachePath } from "./opfsByteStore";
import { IncrementalSha256 } from "./sha256";
import type { AccessLease, CachePrincipal } from "./types";

const WRITE_LEASE_MS = 10 * 60_000;
const MANIFEST_PROGRESS_INTERVAL_BYTES = 1024 * 1024;

export type PartialFileWrite = {
  descriptor: FileCacheDescriptor;
  etag: string;
  hash: IncrementalSha256;
  path: string;
  writtenBytes: number;
};

export class FileCacheWriter {
  private readonly partials = new Map<string, PartialFileWrite>();
  private readonly sessionId: string;

  constructor(private readonly options: {
    bytes: FileCacheByteStore;
    getAccessLease: () => AccessLease | undefined;
    manifest: FileCacheManifestStore;
    now: () => number;
    principal: CachePrincipal;
    telemetry: (event: FileCacheTelemetryEvent) => void;
  }) {
    this.sessionId = globalThis.crypto?.randomUUID?.()
      ?? `file-cache-${options.now()}-${Math.random().toString(16).slice(2)}`;
  }

  partial(key: string): PartialFileWrite | undefined {
    return this.partials.get(key);
  }

  create(key: string, descriptor: FileCacheDescriptor, etag: string): PartialFileWrite {
    const partial = {
      descriptor,
      etag,
      hash: new IncrementalSha256(),
      path: opaqueFileCachePath(),
      writtenBytes: 0,
    };
    this.partials.set(key, partial);
    return partial;
  }

  async readPrefix(key: string, partial: PartialFileWrite): Promise<Blob | null> {
    const blob = await this.options.bytes.read(partial.path);
    if (!blob || blob.size !== partial.writtenBytes) {
      await this.discard(key);
      return null;
    }
    return blob;
  }

  async write(key: string, partial: PartialFileWrite, response: Response, signal: AbortSignal): Promise<void> {
    if (!response.body) return;
    const reader = response.body.getReader();
    let writer: Awaited<ReturnType<FileCacheByteStore["createWriter"]>> | null = null;
    let lastPersisted = partial.writtenBytes;
    let retainForResume = false;
    try {
      writer = await this.options.bytes.createWriter(partial.path, partial.writtenBytes);
      await this.options.manifest.put(this.writingRecord(key, partial, this.options.now()));
      this.options.telemetry({ bytes: partial.descriptor.sizeBytes - partial.writtenBytes, kind: "write" });
      while (true) {
        if (signal.aborted) throw signal.reason ?? new DOMException("File cache write cancelled.", "AbortError");
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try {
          chunk = await reader.read();
        } catch (error) {
          retainForResume = true;
          throw error;
        }
        const { done, value } = chunk;
        if (done) break;
        await writer.write(value);
        partial.hash.update(value);
        partial.writtenBytes += value.byteLength;
        if (partial.writtenBytes - lastPersisted >= MANIFEST_PROGRESS_INTERVAL_BYTES) {
          await this.options.manifest.put(this.writingRecord(key, partial, this.options.now()));
          lastPersisted = partial.writtenBytes;
        }
      }
      await writer.close();
      writer = null;
    } catch (error) {
      await writer?.close().catch(() => undefined);
      if (isAbortError(error) || !retainForResume) {
        await reader.cancel(error).catch(() => undefined);
        await this.discard(key);
      } else if (this.partials.get(key) === partial) {
        await this.options.manifest.put(this.writingRecord(key, partial, this.options.now())).catch(() => undefined);
      }
      throw error;
    }
    try {
      await this.publishReady(key, partial);
    } catch (error) {
      if (this.partials.get(key) === partial
          && partial.writtenBytes >= partial.descriptor.sizeBytes) {
        await this.discard(key);
      }
      throw error;
    }
  }

  async discard(key: string): Promise<void> {
    const partial = this.partials.get(key);
    this.partials.delete(key);
    if (partial) await this.options.bytes.delete(partial.path).catch(() => undefined);
    const record = await this.options.manifest.get(key).catch(() => null);
    if (record?.state === "writing") {
      await this.options.bytes.delete(record.opfsPath).catch(() => undefined);
      await this.options.manifest.delete(key).catch(() => false);
    }
  }

  async deleteRecord(record: FileCacheRecord): Promise<void> {
    await this.options.bytes.delete(record.opfsPath);
    await this.options.manifest.delete(record.key);
  }

  dispose(): void {
    this.partials.clear();
  }

  private async publishReady(key: string, partial: PartialFileWrite): Promise<void> {
    if (partial.writtenBytes !== partial.descriptor.sizeBytes) {
      await this.options.manifest.put(this.writingRecord(key, partial, this.options.now()));
      throw transportError("Storage file response ended before the declared size.");
    }
    const digest = partial.hash.hexDigest();
    if (partial.descriptor.expectedSha256 && partial.descriptor.expectedSha256 !== digest) {
      await this.discard(key);
      throw new Error("Storage file response digest did not match its stable version.");
    }
    const readyAt = this.options.now();
    const ready: FileCacheRecord = {
      ...this.options.principal,
      ...this.accessLeaseMetadata(partial.descriptor),
      cachedAt: readyAt,
      contentType: partial.descriptor.contentType,
      dataClass: partial.descriptor.dataClass,
      etag: partial.etag,
      fileId: partial.descriptor.fileId,
      key,
      lastAccessedAt: readyAt,
      lastVerifiedAt: readyAt,
      opfsPath: partial.path,
      policyRevision: PWA_FILE_CACHE_POLICY_REVISION,
      provenance: partial.descriptor.provenance,
      schemaVersion: PWA_FILE_CACHE_SCHEMA_VERSION,
      sha256: digest,
      sizeBytes: partial.descriptor.sizeBytes,
      sourceVersion: partial.descriptor.sourceVersion,
      state: "ready",
      writtenBytes: partial.writtenBytes,
    };
    await this.options.manifest.put(ready);
    this.partials.delete(key);
    await this.removeObsoleteVersions(ready);
    this.options.telemetry({ bytes: ready.sizeBytes, kind: "ready" });
  }

  private writingRecord(key: string, partial: PartialFileWrite, now: number): FileCacheRecord {
    return {
      ...this.options.principal,
      ...this.accessLeaseMetadata(partial.descriptor),
      cachedAt: now,
      contentType: partial.descriptor.contentType,
      dataClass: partial.descriptor.dataClass,
      etag: partial.etag,
      fileId: partial.descriptor.fileId,
      key,
      lastAccessedAt: now,
      lastVerifiedAt: 0,
      opfsPath: partial.path,
      policyRevision: PWA_FILE_CACHE_POLICY_REVISION,
      provenance: partial.descriptor.provenance,
      schemaVersion: PWA_FILE_CACHE_SCHEMA_VERSION,
      sha256: "",
      sizeBytes: partial.descriptor.sizeBytes,
      sourceVersion: partial.descriptor.sourceVersion,
      state: "writing",
      writtenBytes: partial.writtenBytes,
      writeLeaseExpiresAt: now + WRITE_LEASE_MS,
      writerSessionId: this.sessionId,
    };
  }

  private accessLeaseMetadata(descriptor: FileCacheDescriptor): { accessLeaseExpiresAt?: number } {
    return descriptor.dataClass === "public" ? {} : { accessLeaseExpiresAt: this.options.getAccessLease()?.expiresAt };
  }

  private async removeObsoleteVersions(ready: FileCacheRecord): Promise<void> {
    const records = await this.options.manifest.list({
      appId: ready.appId,
      fileId: ready.fileId,
      userId: ready.userId,
      workspaceId: ready.workspaceId,
    });
    for (const record of records) {
      if (record.key !== ready.key) await this.deleteRecord(record);
    }
  }
}
