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
  cacheErrorReason,
  combinedSignal,
  fetchFileResponse,
  isAbortError,
  networkBlobResult,
  retryableFileStatus,
  transportError,
  typedBlob,
  validResumeResponse,
} from "./fileCacheNetwork";
import { pendingFileCacheCleanupFilters } from "./fileCleanupBarrier";
import { IndexedDbFileCacheManifestStore } from "./fileManifestStore";
import { FileCacheWriter } from "./fileCacheWriter";
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
    const promise = this.openCoordinated(normalizedRequest, key)
      .finally(() => {
        if (this.inFlight.get(key) === promise) this.inFlight.delete(key);
      });
    this.inFlight.set(key, promise);
    return promise;
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
          const hit = await this.readReadyRecord(key, request.descriptor);
          if (hit) return hit;
          this.telemetry({ kind: "miss" });
          persist = await this.canPersist(request.descriptor, key);
          if (!persist) await this.writer?.discard(key).catch(() => undefined);
        }
      } catch (error) {
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

  private async readReadyRecord(key: string, descriptor: FileCacheDescriptor): Promise<FileCacheOpenResult | null> {
    if (!this.manifest || !this.bytes) return null;
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
    const now = this.now();
    await this.manifest.put({ ...record, lastAccessedAt: now, lastVerifiedAt: now }).catch(() => undefined);
    this.telemetry({ bytes: record.sizeBytes, kind: "hit" });
    return {
      blob: typedBlob(blob, descriptor.contentType),
      etag: record.etag,
      source: "cache",
    };
  }

  private async canPersist(descriptor: FileCacheDescriptor, key: string): Promise<boolean> {
    if (!this.manifest || !this.bytes) return false;
    const partial = this.writer?.partial(key);
    const additionalBytes = Math.max(0, descriptor.sizeBytes - (partial?.writtenBytes ?? 0));
    if (!await this.quota.canWrite(additionalBytes)) return false;
    if (!this.writer) return false;
    return enforceFileCacheBudget({
      deleteRecord: (record) => this.writer?.deleteRecord(record) ?? Promise.resolve(),
      descriptor,
      globalBudgetBytes: this.globalBudgetBytes,
      manifest: this.manifest,
      maxScopeBytes: this.maxScopeBytes,
      principal: this.principal,
      targetKey: key,
      telemetry: this.telemetry,
    });
  }

  private async readNetworkWithCache(
    request: FileCacheOpenRequest,
    key: string,
    signal: AbortSignal,
  ): Promise<FileCacheOpenResult> {
    let partial = this.writer?.partial(key);
    const headers = new Headers();
    if (partial) {
      headers.set("Range", `bytes=${partial.writtenBytes}-`);
      headers.set("If-Range", partial.etag);
    }
    let response = await fetchFileResponse(this.fetchImpl, request.url, signal, headers);
    if (partial && response.status === 206) {
      if (!validResumeResponse(response, partial, request.descriptor.sizeBytes)) {
        await this.writer?.discard(key);
        partial = undefined;
        response = await fetchFileResponse(this.fetchImpl, request.url, signal);
      }
    } else if (partial && response.status === 200) {
      await this.writer?.discard(key);
      partial = undefined;
    } else if (partial && (response.status === 412 || response.status === 416)) {
      await this.writer?.discard(key);
      partial = undefined;
      response = await fetchFileResponse(this.fetchImpl, request.url, signal);
    } else if (partial && !retryableFileStatus(response.status)) {
      await this.writer?.discard(key);
      partial = undefined;
    }
    if (!response.ok) throw new MaverickFileHttpError(response);
    if (response.status === 206 && !partial) {
      throw transportError("Storage returned an unsolicited partial file response.");
    }

    const etag = response.headers.get("ETag")?.trim() ?? "";
    if (!isStrongEtag(etag) || !response.body) {
      if (partial) await this.writer?.discard(key);
      return networkBlobResult(response, etag);
    }
    let prefix: Blob | null = null;
    try {
      prefix = partial ? await this.writer?.readPrefix(key, partial) ?? null : null;
    } catch (error) {
      this.persistenceUnavailable = true;
      this.telemetry({ kind: "error", reason: cacheErrorReason(error) });
      await this.writer?.discard(key).catch(() => undefined);
      response.body.cancel().catch(() => undefined);
      return this.readNetwork(request.url, signal);
    }
    if (partial && !prefix) {
      response.body.cancel().catch(() => undefined);
      return this.readNetworkWithCache({ ...request, signal }, key, signal);
    }
    if (!this.writer) return networkBlobResult(response, etag);
    const active = partial ?? this.writer.create(key, request.descriptor, etag);
    let cacheResponse: Response;
    try {
      cacheResponse = response.clone();
    } catch {
      await this.writer.discard(key).catch(() => undefined);
      return networkBlobResult(response, etag);
    }
    const cacheCompletion = this.writer.write(key, active, cacheResponse, signal)
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
