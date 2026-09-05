import { issueFileReadRetryExecutor, type FileReadRetryExecutor } from "./fileReadRetry";
import { withCrossClientLock } from "./cacheBus";
import { enforceFileCacheBudget } from "./fileCacheBudget";
import {
  fileCacheDescriptorIsEligible,
  fileCacheKey,
  isStrongEtag,
  recordMatchesDescriptor,
  validateFileCacheDescriptor,
} from "./fileCacheIdentity";
import { BrowserFileCacheMaintenance } from "./fileCacheMaintenance";
import {
  MaverickFileHttpError,
  MaverickFileRevalidationError,
  cacheErrorReason,
  combinedSignal,
  fetchFileResponse,
  isAbortError,
  networkBlobResult,
  revalidateFileResponse,
  retryableFileStatus,
  transportError,
  typedBlob,
  validResumeResponse,
} from "./fileCacheNetwork";
import { pendingFileCacheCleanupFilters } from "./fileCleanupBarrier";
import { IndexedDbFileCacheManifestStore } from "./fileManifestStore";
import { FileCacheWriter } from "./fileCacheWriter";
import type { PartialFileWrite } from "./fileCacheWriter";
import {
  fileCacheCrossClientCoordinationAvailable,
  runCoordinatedFileCacheWrite,
} from "./fileCacheWriteCoordination";
import { OpfsFileCacheByteStore } from "./opfsByteStore";
import { sha256Blob } from "./sha256";
import { BrowserStorageQuotaAdapter } from "./quota";
import { validatePrincipal } from "./scope";
import {
  DEFAULT_PWA_FILE_CACHE_GLOBAL_BUDGET_BYTES,
  DEFAULT_PWA_FILE_CACHE_MAX_ENTRY_BYTES,
  DEFAULT_PWA_FILE_CACHE_SCOPE_BUDGET_BYTES,
  type FileCacheByteStore,
  type FileCacheDescriptor,
  type FileCacheManifestStore,
  type FileCacheOpenRequest,
  type FileCacheOpenResult,
  type PwaFileCacheOptions,
} from "./fileCacheTypes";
import type { AccessLease, CachePrincipal, StorageQuotaAdapter } from "./types";

const TRUSTED_FILE_CACHES = new WeakSet<PwaFileCache>();
const TRUSTED_FILE_CACHE_HOSTS = new WeakMap<PwaFileCacheHost, CachePrincipal>();
export class PwaFileCacheHost {
  constructor(principal: CachePrincipal) {
    assertTopLevelHostContext();
    TRUSTED_FILE_CACHE_HOSTS.set(this, validatePrincipal(principal));
  }

  createCache(options: PwaFileCacheOptions = {}): PwaFileCache {
    return new PwaFileCache(options, this);
  }
}

export class PwaFileCache {
  readonly appId: string;
  readonly userId: string;
  readonly workspaceId: string;
  private accessLease?: AccessLease;
  private readonly bytes: FileCacheByteStore | null;
  private readonly disposeController = new AbortController();
  private readonly enabled: boolean;
  private readonly fetchImpl: typeof fetch;
  private readonly globalBudgetBytes: number;
  private readonly inFlight = new Map<string, Promise<FileCacheOpenResult>>();
  private initializePromise: Promise<void> | null = null;
  private readonly manifest: FileCacheManifestStore | null;
  private readonly maxEntryBytes: number;
  private readonly maxScopeBytes: number;
  private readonly now: () => number;
  private persistenceUnavailable = false;
  private readonly principal: CachePrincipal;
  private readonly quota: StorageQuotaAdapter;
  private readonly telemetry: NonNullable<PwaFileCacheOptions["telemetry"]>;
  private readonly writer: FileCacheWriter | null;

  constructor(options: PwaFileCacheOptions, host: PwaFileCacheHost) {
    const principal = TRUSTED_FILE_CACHE_HOSTS.get(host);
    if (!principal) throw new TypeError("PWA file-cache clients require a host-attested scope.");
    TRUSTED_FILE_CACHES.add(this);
    this.principal = principal;
    this.userId = principal.userId;
    this.workspaceId = principal.workspaceId;
    this.appId = principal.appId;
    this.enabled = options.enabled === true;
    this.accessLease = options.accessLease;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.now = options.now ?? Date.now;
    this.quota = options.quotaAdapter ?? new BrowserStorageQuotaAdapter();
    this.telemetry = options.telemetry ?? (() => undefined);
    this.maxEntryBytes = positiveBudget(options.maxEntryBytes, DEFAULT_PWA_FILE_CACHE_MAX_ENTRY_BYTES);
    this.maxScopeBytes = positiveBudget(options.maxScopeBytes, DEFAULT_PWA_FILE_CACHE_SCOPE_BUDGET_BYTES);
    this.globalBudgetBytes = positiveBudget(options.globalBudgetBytes, DEFAULT_PWA_FILE_CACHE_GLOBAL_BUDGET_BYTES);
    const stores = browserStores(options);
    this.manifest = stores.manifest;
    this.bytes = stores.bytes;
    this.writer = this.manifest && this.bytes ? new FileCacheWriter({
      bytes: this.bytes,
      getAccessLease: () => this.accessLease,
      manifest: this.manifest,
      now: this.now,
      principal: this.principal,
      telemetry: this.telemetry,
    }) : null;
  }

  open(request: FileCacheOpenRequest): Promise<FileCacheOpenResult> {
    const descriptor = validateFileCacheDescriptor(request.descriptor);
    const normalizedRequest = { ...request, descriptor };
    const key = fileCacheKey(this.principal, descriptor);
    const existing = this.inFlight.get(key);
    if (existing) return existing;
    let promise!: Promise<FileCacheOpenResult>;
    const removeInFlight = () => {
      if (this.inFlight.get(key) === promise) this.inFlight.delete(key);
    };
    promise = this.openCoordinated(normalizedRequest, key).then(
      (result) => {
        if (result.cacheCompletion) {
          return { ...result, cacheCompletion: result.cacheCompletion.finally(removeInFlight) };
        }
        removeInFlight();
        return result;
      },
      (error) => {
        removeInFlight();
        throw error;
      },
    );
    this.inFlight.set(key, promise);
    return promise;
  }

  retryableRead(request: Omit<FileCacheOpenRequest, "signal">): FileReadRetryExecutor {
    if (!TRUSTED_FILE_CACHES.has(this)) throw new TypeError("File retries require a host-attested cache.");
    const descriptor = validateFileCacheDescriptor(structuredClone(request.descriptor));
    const url = request.url;
    if (!/^\/api\/apps\/storage\/media\?/u.test(url) || /[\s#]/u.test(url)) {
      throw new TypeError("Retryable file reads require the Storage media endpoint.");
    }
    return issueFileReadRetryExecutor(
      JSON.stringify([fileCacheKey(this.principal, descriptor), url]),
      (signal) => PwaFileCache.prototype.open.call(this, { descriptor, url, signal }),
    );
  }

  updateAccessLease(lease: AccessLease | undefined): void {
    this.accessLease = lease;
  }

  dispose(): void {
    this.disposeController.abort(new DOMException("PWA file-cache host disposed.", "AbortError"));
    this.inFlight.clear();
    this.writer?.dispose();
  }

  private async openCoordinated(request: FileCacheOpenRequest, key: string): Promise<FileCacheOpenResult> {
    const signal = combinedSignal(request.signal, this.disposeController.signal);
    if (!this.cacheAvailable(request.descriptor)) {
      return this.readNetwork(request.url, signal);
    }
    return withCrossClientLock(`file:${key}`, async () => {
      let persist = false;
      try {
        await this.initialize();
        if (!cleanupBlocksPrincipal(this.principal)) {
          const hit = await this.readReadyRecord(key, request, signal);
          if (hit) return hit;
          this.telemetry({ kind: "miss" });
          persist = Boolean(await this.reserveForPersistence(request.descriptor, key));
        }
      } catch (error) {
        if (isAbortError(error)
            || error instanceof MaverickFileHttpError
            || error instanceof MaverickFileRevalidationError) throw error;
        this.persistenceUnavailable = true;
        this.telemetry({ kind: "error", reason: cacheErrorReason(error) });
      }
      return persist
        ? this.readNetworkWithCache(request, key, signal)
        : this.readNetwork(request.url, signal);
    });
  }

  private cacheAvailable(descriptor: FileCacheDescriptor): boolean {
    return this.enabled
      && !this.persistenceUnavailable
      && Boolean(this.manifest && this.bytes?.available())
      && fileCacheCrossClientCoordinationAvailable()
      && descriptor.sizeBytes <= this.maxEntryBytes
      && fileCacheDescriptorIsEligible(descriptor, this.accessLease, this.now(), this.appId);
  }

  private async initialize(): Promise<void> {
    if (!this.manifest || !this.bytes) return;
    if (!this.initializePromise) {
      const maintenance = new BrowserFileCacheMaintenance(this.manifest, this.bytes, this.now);
      this.initializePromise = maintenance.initialize();
    }
    await this.initializePromise;
  }

  private async readReadyRecord(
    key: string,
    request: FileCacheOpenRequest,
    signal: AbortSignal,
  ): Promise<FileCacheOpenResult | null> {
    if (!this.manifest || !this.bytes) return null;
    const descriptor = request.descriptor;
    const record = await this.manifest.get(key);
    if (!record) return null;
    if (record.state === "writing") return null;
    if (!recordMatchesDescriptor(record, this.principal, descriptor, this.accessLease, this.now())) {
      await this.writer?.deleteRecord(record).catch(() => undefined);
      this.telemetry({ kind: "error", reason: "manifest-invalid" });
      return null;
    }
    const blob = await this.bytes.read(record.opfsPath);
    if (!blob || blob.size !== record.sizeBytes || await sha256Blob(blob) !== record.sha256) {
      await this.writer?.deleteRecord(record).catch(() => undefined);
      this.telemetry({ kind: "error", reason: "bytes-invalid" });
      return null;
    }
    let revalidation: "unavailable" | "verified";
    try {
      revalidation = await revalidateFileResponse(
        this.fetchImpl,
        request.url,
        signal,
        record.etag,
        record.sizeBytes,
      );
    } catch (error) {
      await this.writer?.deleteRecord(record).catch(() => undefined);
      this.telemetry({ kind: "error", reason: "revalidation-rejected" });
      throw error;
    }
    const now = this.now();
    const retained = await this.manifest.updateReady({
      ...record,
      lastAccessedAt: now,
      lastVerifiedAt: revalidation === "verified" ? now : record.lastVerifiedAt,
    });
    if (!retained) return null;
    this.telemetry({ bytes: record.sizeBytes, kind: "hit" });
    return {
      blob: typedBlob(blob, descriptor.contentType),
      etag: record.etag,
      source: "cache",
    };
  }

  private async reserveForPersistence(
    descriptor: FileCacheDescriptor,
    key: string,
  ): Promise<PartialFileWrite | undefined> {
    if (!this.manifest || !this.bytes) return undefined;
    const partial = this.writer?.partial(key);
    const additionalBytes = Math.max(0, descriptor.sizeBytes - (partial?.writtenBytes ?? 0));
    if (!await this.quota.canWrite(additionalBytes)) return undefined;
    if (!this.writer) return undefined;
    return withCrossClientLock("file-cache:budget", async () => {
      const reservation = await this.writer?.reserve(key, descriptor);
      if (!reservation) return undefined;
      const withinBudget = await enforceFileCacheBudget({
        deleteRecord: (record) => this.writer?.deleteRecord(record) ?? Promise.resolve(),
        descriptor,
        globalBudgetBytes: this.globalBudgetBytes,
        manifest: this.manifest!,
        maxScopeBytes: this.maxScopeBytes,
        principal: this.principal,
        targetKey: key,
        telemetry: this.telemetry,
      });
      if (withinBudget) return reservation;
      await this.writer?.discard(key, reservation);
      return undefined;
    });
  }

  private async readNetworkWithCache(
    request: FileCacheOpenRequest,
    key: string,
    signal: AbortSignal,
  ): Promise<FileCacheOpenResult> {
    let partial = this.writer?.partial(key);
    let resuming = Boolean(partial && partial.writtenBytes > 0 && isStrongEtag(partial.etag));
    const headers = new Headers();
    if (resuming && partial) {
      headers.set("Range", `bytes=${partial.writtenBytes}-`);
      headers.set("If-Range", partial.etag);
    }
    let response: Response;
    try {
      response = await fetchFileResponse(this.fetchImpl, request.url, signal, headers);
    } catch (error) {
      if (partial && !resuming) await this.writer?.discard(key, partial);
      throw error;
    }
    if (resuming && partial && response.status === 206) {
      if (!validResumeResponse(response, partial, request.descriptor.sizeBytes)) {
        await this.writer?.discard(key, partial);
        partial = await this.reserveForPersistence(request.descriptor, key);
        resuming = false;
        void response.body?.cancel().catch(() => undefined);
        response = await fetchFileResponse(this.fetchImpl, request.url, signal);
      }
    } else if (resuming && partial && response.status === 200) {
      await this.writer?.discard(key, partial);
      partial = await this.reserveForPersistence(request.descriptor, key);
      resuming = false;
    } else if (resuming && partial && (response.status === 412 || response.status === 416)) {
      await this.writer?.discard(key, partial);
      partial = await this.reserveForPersistence(request.descriptor, key);
      resuming = false;
      void response.body?.cancel().catch(() => undefined);
      response = await fetchFileResponse(this.fetchImpl, request.url, signal);
    } else if (partial && !response.ok && !retryableFileStatus(response.status)) {
      await this.writer?.discard(key, partial);
      partial = undefined;
      resuming = false;
    }
    if (!response.ok) {
      if (partial && !resuming) await this.writer?.discard(key, partial);
      throw new MaverickFileHttpError(response);
    }
    if (response.status === 206 && !resuming) {
      if (partial) await this.writer?.discard(key, partial);
      throw transportError("Storage returned an unsolicited partial file response.");
    }

    const etag = response.headers.get("ETag")?.trim() ?? "";
    if (!isStrongEtag(etag) || !response.body) {
      if (partial) await this.writer?.discard(key, partial);
      return networkBlobResult(response, etag);
    }
    if (partial && !resuming) partial.etag = etag;
    let prefix: Blob | null = null;
    try {
      prefix = resuming && partial ? await this.writer?.readPrefix(key, partial) ?? null : null;
    } catch (error) {
      this.persistenceUnavailable = true;
      this.telemetry({ kind: "error", reason: cacheErrorReason(error) });
      if (partial) await this.writer?.discard(key, partial).catch(() => undefined);
      response.body.cancel().catch(() => undefined);
      return this.readNetwork(request.url, signal);
    }
    if (resuming && partial && !prefix) {
      response.body.cancel().catch(() => undefined);
      return this.readNetworkWithCache({ ...request, signal }, key, signal);
    }
    if (!this.writer) return networkBlobResult(response, etag);
    const active = partial;
    if (!active) return networkBlobResult(response, etag);
    let cacheResponse: Response;
    try {
      cacheResponse = response.clone();
    } catch {
      await this.writer.discard(key, active).catch(() => undefined);
      return networkBlobResult(response, etag);
    }
    const writeFilter = { ...this.principal, fileId: request.descriptor.fileId, sourceVersion: request.descriptor.sourceVersion };
    const cacheCompletion = runCoordinatedFileCacheWrite(writeFilter, signal, (writeSignal) =>
      withCrossClientLock(fileIdentityLockKey(this.principal, request.descriptor.fileId), () =>
        this.writer!.write(key, active, cacheResponse, writeSignal)))
      .then(() => this.enforcePostPublishBudget(request.descriptor, key))
      .catch((error) => {
        this.telemetry({ kind: "error", reason: cacheErrorReason(error) });
      });
    let suffix: Blob;
    try {
      suffix = await response.blob();
    } catch (error) {
      if (isAbortError(error) || signal.aborted) throw error;
      throw transportError("Storage file response stream failed.", error);
    }
    const blob = typedBlob(prefix ? new Blob([prefix, suffix]) : suffix, request.descriptor.contentType);
    if (blob.size !== request.descriptor.sizeBytes) {
      this.telemetry({ kind: "error", reason: "network-size-mismatch" });
    }
    return { blob, cacheCompletion, etag, source: "network" };
  }

  private async enforcePostPublishBudget(descriptor: FileCacheDescriptor, key: string): Promise<void> {
    if (!this.manifest || !this.writer) return;
    await withCrossClientLock("file-cache:budget", async () => {
      const record = await this.manifest?.get(key);
      if (!record || record.state !== "ready") return;
      const withinBudget = await enforceFileCacheBudget({
        deleteRecord: (victim) => this.writer?.deleteRecord(victim) ?? Promise.resolve(),
        descriptor,
        globalBudgetBytes: this.globalBudgetBytes,
        manifest: this.manifest!,
        maxScopeBytes: this.maxScopeBytes,
        principal: this.principal,
        targetKey: key,
        telemetry: this.telemetry,
      });
      if (!withinBudget) {
        await this.writer?.deleteRecord(record);
        this.telemetry({ bytes: record.sizeBytes, count: 1, kind: "evict", reason: "post-publish-budget" });
      }
    });
  }

  private async readNetwork(url: string, signal: AbortSignal): Promise<FileCacheOpenResult> {
    const response = await fetchFileResponse(this.fetchImpl, url, signal);
    if (!response.ok) throw new MaverickFileHttpError(response);
    return networkBlobResult(response, response.headers.get("ETag")?.trim() ?? "");
  }
}

export function createPwaFileCacheHost(principal: CachePrincipal): PwaFileCacheHost {
  return new PwaFileCacheHost(principal);
}

function browserStores(options: PwaFileCacheOptions): {
  bytes: FileCacheByteStore | null;
  manifest: FileCacheManifestStore | null;
} {
  if (options.byteStore || options.manifestStore) {
    return {
      bytes: options.byteStore ?? null,
      manifest: options.manifestStore ?? null,
    };
  }
  try {
    return {
      bytes: new OpfsFileCacheByteStore(),
      manifest: new IndexedDbFileCacheManifestStore(),
    };
  } catch {
    return { bytes: null, manifest: null };
  }
}

function cleanupBlocksPrincipal(principal: CachePrincipal): boolean {
  return pendingFileCacheCleanupFilters().some((filter) =>
    (filter.userId === undefined || filter.userId === principal.userId)
    && (filter.workspaceId === undefined || filter.workspaceId === principal.workspaceId)
    && (filter.appId === undefined || filter.appId === principal.appId));
}

function fileIdentityLockKey(principal: CachePrincipal, fileId: string): string {
  return `file-identity:${JSON.stringify([principal.userId, principal.workspaceId, principal.appId, fileId])}`;
}

function positiveBudget(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}

function assertTopLevelHostContext(): void {
  if (typeof window !== "undefined") {
    if (window.top !== window) {
      throw new Error("The PWA file cache is parent-mediated and cannot be hosted by an embedded app frame.");
    }
    return;
  }
  if (typeof globalThis.indexedDB !== "undefined") {
    throw new Error("The PWA file-cache host is unavailable in browser worker contexts.");
  }
}
