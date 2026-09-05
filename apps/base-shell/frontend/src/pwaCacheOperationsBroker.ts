import {
  PWA_CACHE_OPERATIONS_ACCEPTED,
  PWA_CACHE_OPERATIONS_RESULT,
  isParentPwaCacheOperationsRequest,
  type CacheCleanupResult,
  type CacheDiagnostics,
  type ParentPwaCacheOperationsAcceptedMessage,
  type ParentPwaCacheOperationsRequestMessage,
  type ParentPwaCacheOperationsResultMessage,
  type PwaCacheMetricsSnapshot,
} from "@maverick/pwa-cache";
import {
  registeredMaverickFrameIdentity,
  sameMaverickFrameScope,
  type MaverickFrameScope,
} from "./iframePolicy";
import { shellCacheLifecycle, shellPwaMetrics } from "./pwaCacheRuntime";

type CacheOperationsLifecycle = {
  clearAll(): Promise<CacheCleanupResult>;
  diagnostics(): Promise<CacheDiagnostics>;
};

type CacheOperationsMetrics = {
  reset(): void;
  snapshot(): PwaCacheMetricsSnapshot;
};

type PwaCacheOperationsBrokerOptions = {
  frameScope: MaverickFrameScope;
  lifecycle?: CacheOperationsLifecycle;
  metrics?: CacheOperationsMetrics;
};

const MAX_ACTIVE_OPERATIONS = 8;

export class PwaCacheOperationsBroker {
  private readonly active = new Map<string, MessagePort>();
  private disposed = false;
  private readonly frameScope: MaverickFrameScope;
  private readonly lifecycle: CacheOperationsLifecycle;
  private readonly metrics: CacheOperationsMetrics;

  constructor(options: PwaCacheOperationsBrokerOptions) {
    this.frameScope = Object.freeze({ ...options.frameScope });
    this.lifecycle = options.lifecycle ?? shellCacheLifecycle;
    this.metrics = options.metrics ?? shellPwaMetrics;
  }

  handleWindowMessage(event: MessageEvent): boolean {
    const raw = messageRecord(event.data);
    if (raw?.type !== "maverick.pwa.cache-operations.request.v1") return false;
    const identity = registeredMaverickFrameIdentity(event);
    if (!identity || identity.ownerAppId !== "settings"
        || !sameMaverickFrameScope(identity.scope, this.frameScope)) return false;
    const port = event.ports.length === 1 ? event.ports[0] : null;
    if (!port) return true;
    if (!isParentPwaCacheOperationsRequest(event.data) || this.disposed) {
      port.close();
      return true;
    }
    const request = event.data;
    if (this.active.has(request.request_id) || this.active.size >= MAX_ACTIVE_OPERATIONS) {
      sendAccepted(port, request);
      sendResult(port, request, "unavailable");
      port.close();
      return true;
    }
    this.active.set(request.request_id, port);
    if (!sendAccepted(port, request)) {
      this.active.delete(request.request_id);
      port.close();
      return true;
    }
    void this.process(port, request);
    return true;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const port of this.active.values()) port.close();
    this.active.clear();
  }

  private async process(port: MessagePort, request: ParentPwaCacheOperationsRequestMessage): Promise<void> {
    try {
      const cleanup = request.action === "clear" ? await this.lifecycle.clearAll() : undefined;
      if (cleanup?.status === "complete" && cleanup.pendingCleanupCount === 0) this.metrics.reset();
      const diagnostics = await this.lifecycle.diagnostics();
      if (this.active.get(request.request_id) !== port) return;
      sendResult(port, request, "ok", {
        ...(cleanup ? { cleanup } : {}),
        dashboard: { diagnostics, metrics: this.metrics.snapshot() },
      });
    } catch {
      if (this.active.get(request.request_id) === port) sendResult(port, request, "error");
    } finally {
      if (this.active.get(request.request_id) === port) this.active.delete(request.request_id);
      port.close();
    }
  }
}

function sendAccepted(port: MessagePort, request: ParentPwaCacheOperationsRequestMessage): boolean {
  try {
    port.postMessage({
      app_id: "settings",
      request_id: request.request_id,
      type: PWA_CACHE_OPERATIONS_ACCEPTED,
    } satisfies ParentPwaCacheOperationsAcceptedMessage);
    return true;
  } catch {
    return false;
  }
}

function sendResult(
  port: MessagePort,
  request: ParentPwaCacheOperationsRequestMessage,
  status: ParentPwaCacheOperationsResultMessage["status"],
  result: Pick<ParentPwaCacheOperationsResultMessage, "cleanup" | "dashboard"> = {},
): void {
  try {
    port.postMessage({
      ...result,
      app_id: "settings",
      request_id: request.request_id,
      status,
      type: PWA_CACHE_OPERATIONS_RESULT,
    } satisfies ParentPwaCacheOperationsResultMessage);
  } catch {
    return;
  }
}

function messageRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}
