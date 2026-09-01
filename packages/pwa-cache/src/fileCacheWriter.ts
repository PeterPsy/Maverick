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
  cleanupEpoch: number;
  descriptor: FileCacheDescriptor;
  etag: string;
  hash: IncrementalSha256;
  path: string;
  writtenBytes: number;
  writeGeneration: number;
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

  async reserve(key: string, descriptor: FileCacheDescriptor): Promise<PartialFileWrite | undefined> {
    const existing = this.partials.get(key);
    if (existing) {
      const retained = await this.options.manifest.updateWriting(
        this.writingRecord(key, existing, this.options.now()),
      ).catch(() => false);
      if (retained) return existing;
      await this.discard(key, existing);
      return undefined;
    }
    const cleanupEpoch = await this.options.manifest.getCleanupEpoch();
    const partial = {
      cleanupEpoch,
      descriptor,
      etag: "",
      hash: new IncrementalSha256(),
      path: opaqueFileCachePath(),
      writtenBytes: 0,
      writeGeneration: 0,
    };
    const reserved = await this.options.manifest.reserveWriting(
      this.writingRecord(key, partial, this.options.now()),
      cleanupEpoch,
    );
    if (!reserved) return undefined;
    partial.cleanupEpoch = reserved.cleanupEpoch;
    partial.writeGeneration = reserved.writeGeneration;
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
    const cancelReader = () => { void reader.cancel(signal.reason).catch(() => undefined); };
    signal.addEventListener("abort", cancelReader, { once: true });
    let writer: Awaited<ReturnType<FileCacheByteStore["createWriter"]>> | null = null;
    let lastPersisted = partial.writtenBytes;
    let retainForResume = false;
    try {
      if (signal.aborted) throw signal.reason ?? new DOMException("File cache write cancelled.", "AbortError");
      if (!await this.options.manifest.updateWriting(this.writingRecord(key, partial, this.options.now()))) {
        throw new DOMException("File cache write was superseded or invalidated by cleanup.", "AbortError");
      }
      writer = await this.options.bytes.createWriter(partial.path, partial.writtenBytes);
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
        if (signal.aborted) throw signal.reason ?? new DOMException("File cache write cancelled.", "AbortError");
        const { done, value } = chunk;
        if (done) break;
        await writer.write(value);
        partial.hash.update(value);
        partial.writtenBytes += value.byteLength;
        if (partial.writtenBytes - lastPersisted >= MANIFEST_PROGRESS_INTERVAL_BYTES) {
          if (!await this.options.manifest.updateWriting(this.writingRecord(key, partial, this.options.now()))) {
            throw new DOMException("File cache write was superseded or invalidated by cleanup.", "AbortError");
          }
          lastPersisted = partial.writtenBytes;
        }
      }
      await writer.close();
      writer = null;
    } catch (error) {
      signal.removeEventListener("abort", cancelReader);
      await writer?.close().catch(() => undefined);
      if (isAbortError(error) || !retainForResume) {
        void reader.cancel(error).catch(() => undefined);
        await this.discard(key, partial);
      } else if (this.partials.get(key) === partial) {
        const retained = await this.options.manifest.updateWriting(
          this.writingRecord(key, partial, this.options.now()),
        ).catch(() => false);
        if (!retained) await this.discard(key, partial);
      }
      throw error;
    }
    signal.removeEventListener("abort", cancelReader);
    try {
      await this.publishReady(key, partial);
    } catch (error) {
      if (this.partials.get(key) === partial
          && partial.writtenBytes >= partial.descriptor.sizeBytes) {
        await this.discard(key, partial);
      }
      throw error;
    }
  }

  async discard(key: string, expected?: PartialFileWrite): Promise<void> {
    const partial = this.partials.get(key);
    if (!partial || (expected && partial !== expected)) return;
    this.partials.delete(key);
    if (partial) await this.options.bytes.delete(partial.path).catch(() => undefined);
    await this.options.manifest.deleteWriting(
      this.writingRecord(key, partial, this.options.now()),
    ).catch(() => false);
  }

  async deleteRecord(record: FileCacheRecord): Promise<void> {
    await this.options.bytes.delete(record.opfsPath);
    await this.options.manifest.delete(record.key);
  }

  dispose(): void {
    // The owning cache aborts active write signals. Keep reservations reachable
    // until their finally paths have discarded or retained them deterministically.
  }

  private async publishReady(key: string, partial: PartialFileWrite): Promise<void> {
    if (partial.writtenBytes !== partial.descriptor.sizeBytes) {
      await this.options.manifest.updateWriting(this.writingRecord(key, partial, this.options.now()));
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
      cleanupEpoch: partial.cleanupEpoch,
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
      writeGeneration: partial.writeGeneration,
      writerSessionId: this.sessionId,
    };
    const published = await this.options.manifest.publishReady(ready);
    if (!published.published) {
      throw new DOMException("File cache write was superseded or invalidated by cleanup.", "AbortError");
    }
    this.partials.delete(key);
    await Promise.all(published.obsoleteRecords.map((record) =>
      this.options.bytes.delete(record.opfsPath).catch(() => undefined)));
    this.options.telemetry({ bytes: ready.sizeBytes, kind: "ready" });
  }

  private writingRecord(key: string, partial: PartialFileWrite, now: number): FileCacheRecord {
    return {
      ...this.options.principal,
      ...this.accessLeaseMetadata(partial.descriptor),
      cachedAt: now,
      cleanupEpoch: partial.cleanupEpoch,
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
      writeGeneration: partial.writeGeneration,
      writeLeaseExpiresAt: now + WRITE_LEASE_MS,
      writerSessionId: this.sessionId,
    };
  }

  private accessLeaseMetadata(descriptor: FileCacheDescriptor): { accessLeaseExpiresAt?: number } {
    return descriptor.dataClass === "public" ? {} : { accessLeaseExpiresAt: this.options.getAccessLease()?.expiresAt };
  }

}
