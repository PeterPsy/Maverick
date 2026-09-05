import {
  LOCAL_PERSISTENCE_POLICY_REVISION,
  PWA_DATA_CACHE_BROKER_ACCEPTED,
  PWA_DATA_CACHE_BROKER_NETWORK_REQUEST,
  PWA_DATA_CACHE_BROKER_RESULT,
  createPwaCacheHost,
  isParentDataCacheCancelMessage,
  isParentDataCacheInvalidateMessage,
  isParentDataCacheNetworkResultMessage,
  isParentDataCacheOpenMessage,
  type AccessLease,
  type CacheLoader,
  type CacheNetworkResult,
  type CachePrincipal,
  type CacheReadResult,
  type ParentDataCacheAcceptedMessage,
  type ParentDataCacheNetworkRequestMessage,
  type ParentDataCacheOpenMessage,
  type ParentDataCacheResultMessage,
  type ParentDataCacheSerializedError,
  type ResourceCachePolicy,
  type CacheTelemetry,
  type StorageQuotaAdapter,
} from "@maverick/pwa-cache";
import {
  isMaverickOwnerMessage,
  registeredMaverickFrameIdentity,
  sameMaverickFrameScope,
  type MaverickFrameScope,
} from "./iframePolicy";
import { dataCacheFeatureEnabled } from "./pwa";
import { revokeShellAuthorization, runShellRead, shellCacheLifecycle } from "./pwaCacheRuntime";

type ResourceDeclaration = {
  aliases: readonly string[];
  policy: ResourceCachePolicy<unknown>;
};

type BrokerResource = {
  get(entityId: string): Promise<CacheReadResult<unknown> | null>;
  invalidate(entityId?: string): Promise<number>;
  readThrough(entityId: string, loader: CacheLoader<unknown>, signal?: AbortSignal): Promise<CacheReadResult<unknown>>;
};

type ActiveRead = {
  controller: AbortController;
  declaration: ResourceDeclaration;
  initialDelivered: boolean;
  network: {
    id: string;
    reject: (error: unknown) => void;
    resolve: (result: CacheNetworkResult<unknown>) => void;
  } | null;
  port: MessagePort;
  request: ParentDataCacheOpenMessage;
  resource: BrokerResource;
};

type PwaDataCacheBrokerOptions = {
  accessLease?: AccessLease;
  featureEnabled?: (signal?: AbortSignal) => Promise<boolean | null>;
  frameScope: MaverickFrameScope;
  principal: Omit<CachePrincipal, "appId">;
  quotaAdapter?: StorageQuotaAdapter;
  telemetry?: CacheTelemetry;
};

const RESOURCE_DECLARATIONS: Readonly<Record<string, Readonly<Record<string, ResourceDeclaration>>>> = {
  "app-store": {
    catalog: declaration({
      aliases: ["records", "catalog"],
      dataClass: "public",
      expiryTtlMs: 86_400_000,
      freshTtlMs: 300_000,
      maxEntryBytes: 1_048_576,
      maxScopeBytes: 4_194_304,
      provenance: "app_reference",
      schemaRevision: "app-store.catalog.v1",
    }),
  },
  "fitness-coach": {
    "sanitized-bootstrap-and-thumbnails": declaration({
      aliases: ["workouts", "exercises", "runs", "view-state"],
      dataClass: "personal_data",
      expiryTtlMs: 86_400_000,
      freshTtlMs: 300_000,
      maxEntryBytes: 524_288,
      maxScopeBytes: 16_777_216,
      provenance: "app_reference",
      schemaRevision: "fitness-coach.sanitized-bootstrap-and-thumbnails.v1",
    }),
  },
  "storage": {
    "file-catalog": declaration({
      aliases: ["files", "drive-connections", "view-state"],
      cacheApproved: true,
      dataClass: "workspace_internal",
      expiryTtlMs: 86_400_000,
      freshTtlMs: 30_000,
      maxEntryBytes: 262_144,
      maxScopeBytes: 16_777_216,
      provenance: "attachment",
      schemaRevision: "storage.file-catalog.v1",
    }),
  },
  "website-studio": {
    "site-snapshots": declaration({
      aliases: [
        "records",
        "source",
        "working-state",
        "navigation",
        "preview",
        "activity",
        "settings",
        "view-selection",
      ],
      cacheApproved: true,
      dataClass: "workspace_internal",
      expiryTtlMs: 86_400_000,
      freshTtlMs: 60_000,
      maxEntryBytes: 2_097_152,
      maxScopeBytes: 16_777_216,
      provenance: "app_reference",
      schemaRevision: "website-studio.site-snapshots.v2",
    }),
  },
};

export class PwaDataCacheBroker {
  private readonly active = new Map<string, ActiveRead>();
  private readonly clients = new Map<string, ReturnType<ReturnType<typeof createPwaCacheHost>["createClient"]>>();
  private readonly featureEnabled: NonNullable<PwaDataCacheBrokerOptions["featureEnabled"]>;
  private readonly frameScope: MaverickFrameScope;
  private featureWasConfirmedEnabled = false;
  private featureWasExplicitlyDisabled = false;
  private authorizationFailureStarted: Promise<void> | null = null;
  private readonly resources = new Map<string, BrokerResource>();
  private disposed = false;

  constructor(options: PwaDataCacheBrokerOptions) {
    if (options.frameScope.workspaceId !== options.principal.workspaceId) {
      throw new Error("PWA data-cache broker frame scope must match its cache principal workspace.");
    }
    this.featureEnabled = options.featureEnabled ?? dataCacheFeatureEnabled;
    this.frameScope = Object.freeze({ ...options.frameScope });
    for (const [appId, declarations] of Object.entries(RESOURCE_DECLARATIONS)) {
      const client = createPwaCacheHost({ ...options.principal, appId }).createClient({
        accessLease: options.accessLease,
        enabled: true,
        quotaAdapter: options.quotaAdapter,
        telemetry: options.telemetry,
      });
      this.clients.set(appId, client);
      for (const [resourceName, resourceDeclaration] of Object.entries(declarations)) {
        this.resources.set(resourceKey(appId, resourceName), client.resource(resourceName, resourceDeclaration.policy));
      }
    }
  }

  handleWindowMessage(
    event: MessageEvent,
    enabledAppIds: ReadonlySet<string>,
  ): boolean {
    const raw = messageRecord(event.data);
    if (raw?.type !== "maverick.pwa.data-cache.open.v1") return false;
    if (!isParentDataCacheOpenMessage(event.data)) {
      event.ports[0]?.close();
      return true;
    }
    const request = event.data;
    const frameIdentity = registeredMaverickFrameIdentity(event);
    if (!frameIdentity) return false;
    const port = event.ports.length === 1 ? event.ports[0] : null;
    const declaration = RESOURCE_DECLARATIONS[request.app_id]?.[request.resource];
    const resource = this.resources.get(resourceKey(request.app_id, request.resource));
    if (!port) return true;
    if (frameIdentity.ownerAppId !== request.app_id
        || !sameMaverickFrameScope(frameIdentity.scope, this.frameScope)
        || !enabledAppIds.has(request.app_id)
        || !declaration
        || !resource
        || this.disposed) {
      sendAccepted(port, request);
      sendResult(port, request, { phase: "initial", status: "unavailable" });
      port.close();
      return true;
    }
    if (declaration.policy.schemaRevision !== request.schema_revision || this.active.has(request.request_id)) {
      sendAccepted(port, request);
      sendResult(port, request, { phase: "initial", status: "unavailable" });
      port.close();
      return true;
    }

    const active: ActiveRead = {
      controller: new AbortController(),
      declaration,
      initialDelivered: false,
      network: null,
      port,
      request,
      resource,
    };
    this.active.set(request.request_id, active);
    port.addEventListener("message", (portEvent) => this.handlePortMessage(active, portEvent.data));
    port.start();
    if (!sendAccepted(port, request)) {
      this.finish(active);
      return true;
    }
    void this.process(active);
    return true;
  }

  handleDataChangedMessage(event: MessageEvent): void {
    const payload = messageRecord(event.data);
    if (!payload
        || payload.type !== "maverick.app.data-changed"
        || typeof payload.owner_app_id !== "string"
        || typeof payload.resource !== "string") return;
    const ownerAppId = payload.owner_app_id;
    if (!isMaverickOwnerMessage(event, ownerAppId, this.frameScope)) return;
    const declarations = RESOURCE_DECLARATIONS[ownerAppId];
    if (!declarations) return;
    for (const [resourceName, resourceDeclaration] of Object.entries(declarations)) {
      if (payload.resource !== resourceName && !resourceDeclaration.aliases.includes(payload.resource)) continue;
      const entityId = payload.resource === resourceName && typeof payload.entity_id === "string"
        ? payload.entity_id
        : undefined;
      for (const active of [...this.active.values()]) {
        if (active.request.app_id !== ownerAppId
            || active.request.resource !== resourceName
            || (entityId && active.request.entity_id !== entityId)) continue;
        this.terminateActive(
          active,
          active.initialDelivered ? "error" : "unavailable",
          new DOMException("PWA data-cache read invalidated by an app event.", "AbortError"),
        );
      }
      void shellCacheLifecycle.handleDataChanged({
        ...(entityId ? { entityId } : {}),
        ownerAppId,
        resource: resourceName,
      }).catch(() => undefined);
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const active of [...this.active.values()]) {
      this.terminateActive(
        active,
        "error",
        new DOMException("PWA data-cache broker disposed.", "AbortError"),
      );
    }
    this.resources.clear();
    for (const client of this.clients.values()) client.dispose();
    this.clients.clear();
  }

  private handlePortMessage(active: ActiveRead, value: unknown): void {
    if (this.active.get(active.request.request_id) !== active) return;
    if (isParentDataCacheCancelMessage(value, active.request.request_id)) {
      active.controller.abort(new DOMException("PWA data-cache read cancelled.", "AbortError"));
      this.finish(active);
      return;
    }
    if (isParentDataCacheInvalidateMessage(value, active.request.request_id)) {
      void active.resource.invalidate(active.request.entity_id).catch(() => undefined);
      active.controller.abort(new DOMException("Invalid app read model rejected.", "AbortError"));
      this.finish(active);
      return;
    }
    const network = active.network;
    if (!network || !isParentDataCacheNetworkResultMessage(
      value,
      active.request.request_id,
      network.id,
    )) return;
    active.network = null;
    if (value.app_id !== active.request.app_id) {
      network.reject(new Error("The data-cache network response app scope did not match."));
      return;
    }
    if (value.status === "error") {
      network.reject(errorFromMessage(value.error));
      return;
    }
    network.resolve(value.kind === "not_modified"
      ? {
          kind: "not_modified",
          ...(value.revision ? { revision: value.revision } : {}),
          ...(value.etag ? { etag: value.etag } : {}),
        }
      : {
          kind: "value",
          payload: value.payload,
          revision: value.revision as string,
          ...(value.etag ? { etag: value.etag } : {}),
        });
  }

  private async process(active: ActiveRead): Promise<void> {
    const { request, resource } = active;
    try {
      const featureDecision = this.featureWasExplicitlyDisabled
        ? false
        : await this.featureEnabled(active.controller.signal).catch(() => null);
      if (active.controller.signal.aborted) return;
      if (featureDecision === true) this.featureWasConfirmedEnabled = true;
      else if (featureDecision === false) {
        this.featureWasExplicitlyDisabled = true;
        this.featureWasConfirmedEnabled = false;
        for (const pending of [...this.active.values()]) {
          this.terminateActive(
            pending,
            pending.initialDelivered ? "error" : "unavailable",
            new DOMException("PWA data-cache rollout was disabled.", "AbortError"),
          );
        }
        return;
      }
      const enabled = featureDecision === true
        || (featureDecision === null && this.featureWasConfirmedEnabled);
      if (!enabled) {
        this.reply(active, { phase: "initial", status: "unavailable" }, true);
        return;
      }

      const migrationCommitted = await this.migrateSeed(active);
      if (active.controller.signal.aborted) return;
      const result = await resource.readThrough(
        request.entity_id,
        (context) => runShellRead(
          `data-cache:${request.app_id}:${request.resource}:${request.entity_id}`,
          (retrySignal) => this.requestNetwork(active, context, retrySignal),
          active.controller.signal,
        ),
        active.controller.signal,
      );
      if (active.controller.signal.aborted) return;
      this.reply(active, {
        freshness: result.freshness,
        has_revalidation: Boolean(result.revalidation),
        migration_committed: migrationCommitted,
        payload: result.payload,
        phase: "initial",
        revision: result.revision,
        source: result.source,
        status: "ok",
      }, !result.revalidation);
      if (!result.revalidation) return;
      try {
        const revalidated = await result.revalidation;
        if (active.controller.signal.aborted) return;
        this.reply(active, {
          changed: revalidated.changed,
          payload: revalidated.payload,
          phase: "revalidation",
          revision: revalidated.revision,
          status: "ok",
        }, true);
      } catch (error) {
        if (!active.controller.signal.aborted) {
          await this.handleReadError(error);
          this.reply(active, { phase: "revalidation", status: "error" }, true);
        }
      }
    } catch (error) {
      if (!active.controller.signal.aborted) {
        await this.handleReadError(error);
        this.reply(active, { phase: "initial", status: "error" }, true);
      }
    } finally {
      if (active.controller.signal.aborted) this.finish(active);
    }
  }

  private async migrateSeed(active: ActiveRead): Promise<boolean> {
    const seed = active.request.migration_seed;
    if (!seed) return false;
    const existing = await active.resource.get(active.request.entity_id);
    if (existing) return true;
    await active.resource.readThrough(active.request.entity_id, async () => ({
      ...(seed.etag ? { etag: seed.etag } : {}),
      kind: "value",
      payload: seed.payload,
      revision: seed.revision,
    }), active.controller.signal);
    const verified = await active.resource.get(active.request.entity_id);
    return Boolean(verified && verified.revision === seed.revision);
  }

  private requestNetwork(
    active: ActiveRead,
    context: Parameters<CacheLoader<unknown>>[0],
    signal: AbortSignal,
  ): Promise<CacheNetworkResult<unknown>> {
    if (signal.aborted) return Promise.reject(abortFromSignal(signal));
    if (active.network) return Promise.reject(new Error("Concurrent data-cache loader requests are not allowed."));
    const networkRequestId = requestIdentity();
    return new Promise((resolve, reject) => {
      const abort = () => {
        if (active.network?.id === networkRequestId) active.network = null;
        reject(abortFromSignal(signal));
      };
      active.network = {
        id: networkRequestId,
        reject: (error) => {
          signal.removeEventListener("abort", abort);
          reject(error);
        },
        resolve: (result) => {
          signal.removeEventListener("abort", abort);
          resolve(result);
        },
      };
      signal.addEventListener("abort", abort, { once: true });
      try {
        active.port.postMessage({
          app_id: active.request.app_id,
          ...(context.etag ? { etag: context.etag } : {}),
          ...(context.knownRevision ? { known_revision: context.knownRevision } : {}),
          network_request_id: networkRequestId,
          request_id: active.request.request_id,
          type: PWA_DATA_CACHE_BROKER_NETWORK_REQUEST,
        } satisfies ParentDataCacheNetworkRequestMessage);
      } catch (error) {
        active.network = null;
        signal.removeEventListener("abort", abort);
        reject(error);
      }
    });
  }

  private async handleReadError(error: unknown): Promise<void> {
    const status = authorizationFailureStatus(error);
    if (!status) return;
    if (!this.authorizationFailureStarted) {
      this.authorizationFailureStarted = this.completeAuthorizationFailure(status);
    }
    await this.authorizationFailureStarted;
  }

  private async completeAuthorizationFailure(status: 401 | 403): Promise<void> {
    this.featureWasExplicitlyDisabled = true;
    this.featureWasConfirmedEnabled = false;
    for (const active of [...this.active.values()]) {
      this.terminateActive(
        active,
        "error",
        new DOMException("PWA data-cache authorization was revoked.", "AbortError"),
      );
    }
    await revokeShellAuthorization(status);
  }

  private reply(
    active: ActiveRead,
    result: Omit<ParentDataCacheResultMessage, "app_id" | "request_id" | "type">,
    finish: boolean,
  ): void {
    if (this.active.get(active.request.request_id) !== active) return;
    sendResult(active.port, active.request, result);
    if (result.phase === "initial") active.initialDelivered = true;
    if (finish) this.finish(active);
  }

  private terminateActive(
    active: ActiveRead,
    status: "error" | "unavailable",
    reason: DOMException,
  ): void {
    if (this.active.get(active.request.request_id) !== active) return;
    sendResult(active.port, active.request, {
      phase: active.initialDelivered ? "revalidation" : "initial",
      status,
    });
    active.controller.abort(reason);
    this.finish(active);
  }

  private finish(active: ActiveRead): void {
    if (this.active.get(active.request.request_id) !== active) return;
    this.active.delete(active.request.request_id);
    active.network?.reject(new DOMException("PWA data-cache read closed.", "AbortError"));
    active.network = null;
    active.port.close();
  }
}

function declaration(options: {
  aliases: readonly string[];
  cacheApproved?: boolean;
  dataClass: ResourceCachePolicy<unknown>["dataClass"];
  expiryTtlMs: number;
  freshTtlMs: number;
  maxEntryBytes: number;
  maxScopeBytes: number;
  provenance: ResourceCachePolicy<unknown>["provenance"];
  schemaRevision: string;
}): ResourceDeclaration {
  return {
    aliases: options.aliases,
    policy: {
      allowStale: true,
      cacheApproved: options.cacheApproved,
      dataClass: options.dataClass,
      expiryTtlMs: options.expiryTtlMs,
      freshTtlMs: options.freshTtlMs,
      maxEntryBytes: options.maxEntryBytes,
      maxScopeBytes: options.maxScopeBytes,
      policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
      provenance: options.provenance,
      revalidateOnRead: "always",
      sanitize: sanitizeStructuredReadModel,
      schemaRevision: options.schemaRevision,
    },
  };
}

function sanitizeStructuredReadModel(payload: unknown): unknown | null {
  if (!payload || typeof payload !== "object" || (!Array.isArray(payload) && Object.getPrototypeOf(payload) !== Object.prototype)) {
    return null;
  }
  return isStructuredJson(payload, 0, new Set()) ? payload : null;
}

function isStructuredJson(value: unknown, depth: number, ancestors: Set<object>): boolean {
  if (depth > 32) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (!value || typeof value !== "object" || ancestors.has(value)) return false;
  if (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype) return false;
  const next = new Set(ancestors).add(value);
  return (Array.isArray(value) ? value : Object.values(value)).every((item) => isStructuredJson(item, depth + 1, next));
}

function errorFromMessage(error: ParentDataCacheSerializedError | undefined): Error {
  if (!error) return new Error("The app data-cache loader failed.");
  if (error.name === "AbortError") return new DOMException("The app data-cache loader was cancelled.", "AbortError");
  const result = new Error("The app data-cache loader failed.") as Error & {
    retryAfterMs?: number;
    status?: number;
  };
  result.name = error.name;
  if (error.status !== undefined) result.status = error.status;
  if (error.retry_after_ms !== undefined) result.retryAfterMs = error.retry_after_ms;
  return result;
}

function authorizationFailureStatus(error: unknown): 401 | 403 | null {
  if (!error || typeof error !== "object") return null;
  const status = (error as { status?: unknown }).status;
  return status === 401 || status === 403 ? status : null;
}

function sendResult(
  port: MessagePort,
  request: Pick<ParentDataCacheOpenMessage, "app_id" | "request_id">,
  result: Omit<ParentDataCacheResultMessage, "app_id" | "request_id" | "type">,
): void {
  try {
    port.postMessage({
      ...result,
      app_id: request.app_id,
      request_id: request.request_id,
      type: PWA_DATA_CACHE_BROKER_RESULT,
    } satisfies ParentDataCacheResultMessage);
  } catch {
    return;
  }
}

function sendAccepted(
  port: MessagePort,
  request: Pick<ParentDataCacheOpenMessage, "app_id" | "request_id">,
): boolean {
  try {
    port.postMessage({
      app_id: request.app_id,
      request_id: request.request_id,
      type: PWA_DATA_CACHE_BROKER_ACCEPTED,
    } satisfies ParentDataCacheAcceptedMessage);
    return true;
  } catch {
    return false;
  }
}

function resourceKey(appId: string, resource: string): string {
  return JSON.stringify([appId, resource]);
}

function requestIdentity(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function messageRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function abortFromSignal(signal: AbortSignal): unknown {
  return signal.reason instanceof Error
    ? signal.reason
    : new DOMException("PWA data-cache read cancelled.", "AbortError");
}
