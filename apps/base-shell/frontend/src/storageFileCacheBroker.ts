import {
  DEFAULT_PWA_FILE_CACHE_MAX_ENTRY_BYTES,
  MaverickFileHttpError,
  PWA_FILE_CACHE_BROKER_ACCEPTED,
  PWA_FILE_CACHE_BROKER_OPEN,
  PWA_FILE_CACHE_BROKER_RESULT,
  PWA_FILE_CACHE_POLICY_REVISION,
  createPwaFileCacheHost,
  isParentFileCacheCancelMessage,
  isParentFileCacheOpenMessage,
  sha256Blob,
  type AccessLease,
  type CachePrincipal,
  type FileCacheDescriptor,
  type FileCacheOpenRequest,
  type FileCacheOpenResult,
  type MaverickDataClass,
  type ParentFileCacheAcceptedMessage,
  type ParentFileCacheOpenMessage,
  type ParentFileCacheResultMessage,
  type PwaFileCache,
} from "@maverick/pwa-cache";
import { readStorageFileCacheDescriptor } from "./api";
import { runShellRead, shellCacheLifecycle } from "./pwaCacheRuntime";
import { storageFileCacheFeatureEnabled } from "./pwa";

const DESCRIPTOR_SCHEMA = "maverick.storage-file-cache-descriptor.v1";
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const DATA_CLASSES = new Set<MaverickDataClass>([
  "public",
  "workspace_internal_fake",
  "workspace_internal",
  "personal_data",
  "regulated_or_customer_data",
  "credential_or_secret",
  "host_operational_metadata",
  "unclassified",
]);

type ResolvedFile = {
  descriptor: FileCacheDescriptor;
  url: string;
};

type StorageFileCacheBrokerOptions = {
  accessLease?: AccessLease;
  featureEnabled?: (signal?: AbortSignal) => Promise<boolean>;
  hostOrigin?: string;
  openFile?: (request: Omit<FileCacheOpenRequest, "signal">, signal: AbortSignal) => Promise<FileCacheOpenResult>;
  principal: CachePrincipal;
  resolveDescriptor?: (request: ParentFileCacheOpenMessage, signal: AbortSignal) => Promise<unknown>;
};

export class StorageFileCacheBroker {
  private readonly active = new Map<string, { controller: AbortController; port: MessagePort }>();
  private readonly cache: PwaFileCache | null;
  private readonly featureEnabled: NonNullable<StorageFileCacheBrokerOptions["featureEnabled"]>;
  private readonly hostOrigin: string;
  private readonly openFile: NonNullable<StorageFileCacheBrokerOptions["openFile"]>;
  private readonly resolveDescriptor: NonNullable<StorageFileCacheBrokerOptions["resolveDescriptor"]>;
  private disposed = false;

  constructor(options: StorageFileCacheBrokerOptions) {
    this.hostOrigin = options.hostOrigin ?? window.location.origin;
    this.featureEnabled = options.featureEnabled ?? storageFileCacheFeatureEnabled;
    this.resolveDescriptor = options.resolveDescriptor ?? ((request, signal) =>
      readStorageFileCacheDescriptor(request.file_id, request.source_version, signal));
    if (options.openFile) {
      this.cache = null;
      this.openFile = options.openFile;
    } else {
      this.cache = createPwaFileCacheHost(options.principal).createCache({
        accessLease: options.accessLease,
        enabled: true,
      });
      this.openFile = (request, signal) => runShellRead(
        `storage:file:${request.descriptor.fileId}:${request.descriptor.sourceVersion}`,
        (retrySignal) => this.cache!.open({ ...request, signal: retrySignal }),
        signal,
      );
    }
  }

  handleWindowMessage(event: MessageEvent, storageFrameWindow: Window | null): boolean {
    const raw = messageRecord(event.data);
    if (raw?.type !== PWA_FILE_CACHE_BROKER_OPEN) return false;
    if (!storageFrameWindow || event.source !== storageFrameWindow) return false;
    if (event.origin !== this.hostOrigin && event.origin !== "null") return false;
    if (!isParentFileCacheOpenMessage(event.data)) return true;
    const port = event.ports.length === 1 ? event.ports[0] : null;
    if (!port || this.disposed) return true;
    const request = event.data;
    if (this.active.has(request.request_id)) {
      sendResult(port, request.request_id, "unavailable");
      port.close();
      return true;
    }

    const controller = new AbortController();
    this.active.set(request.request_id, { controller, port });
    port.addEventListener("message", (portEvent) => {
      if (isParentFileCacheCancelMessage(portEvent.data, request.request_id)) {
        controller.abort(new DOMException("Storage file open was cancelled.", "AbortError"));
      }
    });
    port.start();
    try {
      port.postMessage({
        app_id: "storage",
        request_id: request.request_id,
        type: PWA_FILE_CACHE_BROKER_ACCEPTED,
      } satisfies ParentFileCacheAcceptedMessage);
    } catch {
      this.finish(request.request_id);
      return true;
    }
    void this.process(request, controller.signal);
    return true;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const { controller, port } of this.active.values()) {
      controller.abort(new DOMException("Storage file-cache broker disposed.", "AbortError"));
      port.close();
    }
    this.active.clear();
    this.cache?.dispose();
  }

  private async process(request: ParentFileCacheOpenMessage, signal: AbortSignal): Promise<void> {
    try {
      if (!await this.featureEnabled(signal).catch(() => false)) {
        this.reply(request.request_id, "unavailable");
        return;
      }
      const payload = await this.resolveDescriptor(request, signal).catch(() => null);
      if (signal.aborted) return;
      const resolved = sanitizeDescriptor(payload, request, this.hostOrigin);
      if (!resolved) {
        this.reply(request.request_id, "unavailable");
        return;
      }
      const result = await this.openFile({ descriptor: resolved.descriptor, url: resolved.url }, signal);
      if (signal.aborted) return;
      if (result.blob.size !== resolved.descriptor.sizeBytes
          || (resolved.descriptor.expectedSha256
            && await sha256Blob(result.blob) !== resolved.descriptor.expectedSha256)) {
        this.reply(request.request_id, "error");
        return;
      }
      const active = this.active.get(request.request_id);
      active?.port.postMessage({
        app_id: "storage",
        blob: result.blob,
        request_id: request.request_id,
        source: result.source,
        status: "ok",
        type: PWA_FILE_CACHE_BROKER_RESULT,
      } satisfies ParentFileCacheResultMessage);
      this.finish(request.request_id);
    } catch (error) {
      if (error instanceof MaverickFileHttpError && (error.status === 401 || error.status === 403)) {
        await shellCacheLifecycle.authorizationFailure().catch(() => undefined);
      }
      if (!signal.aborted && !isAbortError(error)) this.reply(request.request_id, "error");
      else this.finish(request.request_id);
    }
  }

  private reply(requestId: string, status: "error" | "unavailable"): void {
    const active = this.active.get(requestId);
    if (!active) return;
    sendResult(active.port, requestId, status);
    this.finish(requestId);
  }

  private finish(requestId: string): void {
    const active = this.active.get(requestId);
    if (!active) return;
    this.active.delete(requestId);
    active.port.close();
  }
}

function sanitizeDescriptor(
  value: unknown,
  request: ParentFileCacheOpenMessage,
  hostOrigin: string,
): ResolvedFile | null {
  const payload = messageRecord(value);
  if (!payload || payload.schema !== DESCRIPTOR_SCHEMA || payload.eligible !== true) return null;
  const policy = messageRecord(payload.policy);
  const file = messageRecord(payload.file);
  if (!policy || !file
      || policy.policy_revision !== PWA_FILE_CACHE_POLICY_REVISION
      || !DATA_CLASSES.has(policy.data_class as MaverickDataClass)
      || policy.provenance !== "attachment"
      || typeof policy.cache_approved !== "boolean"
      || typeof policy.privacy_approved !== "boolean"
      || typeof policy.regulated_allowlisted !== "boolean"
      || file.file_id !== request.file_id
      || file.source_version !== request.source_version
      || !Number.isSafeInteger(file.size_bytes)
      || (file.size_bytes as number) < 0
      || (file.size_bytes as number) > DEFAULT_PWA_FILE_CACHE_MAX_ENTRY_BYTES
      || !validContentType(file.content_type)
      || !validExpectedSha256(file.expected_sha256)) {
    return null;
  }
  const url = validatedMediaUrl(file.media_url, request, hostOrigin);
  if (!url) return null;
  return {
    descriptor: {
      cacheApproved: policy.cache_approved as boolean,
      contentType: file.content_type as string,
      dataClass: policy.data_class as MaverickDataClass,
      ...((file.expected_sha256 as string) ? { expectedSha256: file.expected_sha256 as string } : {}),
      fileId: request.file_id,
      privacyApproved: policy.privacy_approved as boolean,
      provenance: "attachment",
      regulatedAllowlisted: policy.regulated_allowlisted as boolean,
      sizeBytes: file.size_bytes as number,
      sourceVersion: request.source_version,
    },
    url,
  };
}

function validatedMediaUrl(value: unknown, request: ParentFileCacheOpenMessage, hostOrigin: string): string | null {
  if (typeof value !== "string" || !value || value.length > 4_096) return null;
  try {
    const url = new URL(value, hostOrigin);
    if (url.origin !== hostOrigin
        || url.username || url.password || url.hash
        || url.pathname !== "/api/apps/storage/media"
        || url.searchParams.getAll("stable_storage_file_id").length !== 1
        || url.searchParams.get("stable_storage_file_id") !== request.file_id
        || url.searchParams.getAll("source_version").length !== 1
        || url.searchParams.get("source_version") !== request.source_version
        || url.searchParams.get("download") !== "1"
        || url.searchParams.get("_pwa_file_cache") !== "1") {
      return null;
    }
    return `${url.pathname}${url.search}`;
  } catch {
    return null;
  }
}

function validContentType(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255 && !/[\r\n]/u.test(value);
}

function validExpectedSha256(value: unknown): value is string {
  return value === "" || (typeof value === "string" && SHA256_PATTERN.test(value));
}

function sendResult(port: MessagePort, requestId: string, status: "error" | "unavailable"): void {
  try {
    port.postMessage({
      app_id: "storage",
      request_id: requestId,
      status,
      type: PWA_FILE_CACHE_BROKER_RESULT,
    } satisfies ParentFileCacheResultMessage);
  } catch {
    return;
  }
}

function messageRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function isAbortError(error: unknown): boolean {
  return Boolean(error) && typeof error === "object" && (error as { name?: unknown }).name === "AbortError";
}
