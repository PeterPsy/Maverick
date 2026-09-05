import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  readCacheModelJson,
  readThroughParentDataCache,
  PWA_DATA_CACHE_BROKER_ACCEPTED,
  PWA_DATA_CACHE_BROKER_NETWORK_REQUEST,
  PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
  PWA_DATA_CACHE_BROKER_OPEN,
  PWA_DATA_CACHE_BROKER_RESULT,
} from "@maverick/pwa-cache";
import { PwaDataCacheBroker } from "./pwaDataCacheBroker";
import { shellCacheLifecycle, shellRetryCoordinator, subscribeShellAuthorizationRevocation } from "./pwaCacheRuntime";
import { setMaverickFrameOrigin, type MaverickFrameScope } from "./iframePolicy";

type PortMessage = Record<string, unknown>;

const appWindow = {} as Window;
const appOrigin = "https://af-app-store.sidecars.maverick.test";
const appFrame = {
  contentWindow: appWindow,
  dataset: {},
} as unknown as HTMLIFrameElement;
const registeredFrames: HTMLIFrameElement[] = [];
const FRAME_SCOPE = Object.freeze({ sessionGeneration: "session-default", workspaceId: "default" });

function registerFrame(
  frame: HTMLIFrameElement,
  origin: string,
  ownerAppId: string,
  frameScope: MaverickFrameScope = FRAME_SCOPE,
): void {
  setMaverickFrameOrigin(frame, origin, ownerAppId, frameScope);
  registeredFrames.push(frame);
}

function requestEvent(
  channel: MessageChannel,
  overrides: Record<string, unknown> = {},
  sender: { origin: string; source: Window } = { origin: appOrigin, source: appWindow },
): MessageEvent {
  return {
    data: {
      app_id: "app-store",
      entity_id: "visible-catalog",
      request_id: "request-one",
      resource: "catalog",
      schema_revision: "app-store.catalog.v1",
      type: PWA_DATA_CACHE_BROKER_OPEN,
      ...overrides,
    },
    origin: sender.origin,
    ports: [channel.port2],
    source: sender.source,
  } as unknown as MessageEvent;
}

function portMessages(port: MessagePort) {
  const queued: PortMessage[] = [];
  const waiters: Array<(message: PortMessage) => void> = [];
  port.addEventListener("message", (event) => {
    const waiter = waiters.shift();
    if (waiter) waiter(event.data);
    else queued.push(event.data);
  });
  port.start();
  return {
    next(timeoutMs = 1_000): Promise<PortMessage> {
      const queuedMessage = queued.shift();
      if (queuedMessage) return Promise.resolve(queuedMessage);
      return new Promise((resolve, reject) => {
        const timeout = globalThis.setTimeout(() => reject(new Error("Timed out waiting for broker message.")), timeoutMs);
        waiters.push((message) => {
          globalThis.clearTimeout(timeout);
          resolve(message);
        });
      });
    },
  };
}

async function nextOfType(messages: ReturnType<typeof portMessages>, type: string): Promise<PortMessage> {
  while (true) {
    const message = await messages.next();
    if (message.type === type) return message;
  }
}

function broker(
  featureEnabled: () => Promise<boolean | null> = async () => true,
  frameScope: MaverickFrameScope = FRAME_SCOPE,
): PwaDataCacheBroker {
  return new PwaDataCacheBroker({
    featureEnabled,
    frameScope,
    principal: { userId: "user-one", workspaceId: frameScope.workspaceId },
  });
}

describe("Base Shell structured data-cache broker", () => {
  const brokers: PwaDataCacheBroker[] = [];
  const authorizationSubscriptions: Array<() => void> = [];

  beforeEach(() => {
    const shellWindow = new EventTarget() as EventTarget & Window;
    Object.assign(shellWindow, { location: { origin: "https://maverick.test" }, top: shellWindow });
    vi.stubGlobal("window", shellWindow);
    registerFrame(appFrame, appOrigin, "app-store");
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    brokers.splice(0).forEach((item) => item.dispose());
    authorizationSubscriptions.splice(0).forEach((unsubscribe) => unsubscribe());
    registeredFrames.splice(0).forEach((frame) => setMaverickFrameOrigin(frame, null, "cleanup", FRAME_SCOPE));
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it.each(["recovery", "cleanup"])("keeps brokered retry cancellation scoped to the shell: %s", async (outcome) => {
    const subject = broker();
    brokers.push(subject);
    const fetch = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("link down"))
      .mockResolvedValueOnce(Response.json({ revision: "recovered", items: [] }));
    const loader = vi.fn(async ({ signal }: { signal?: AbortSignal }) => {
      const payload = await readCacheModelJson<{ revision: string; items: unknown[] }>({ appId: "app-store", resource: "catalog" }, signal);
      return { kind: "value" as const, payload, revision: payload.revision };
    });
    const result = readThroughParentDataCache({
      appId: "app-store", entityId: "retry-miss", resource: "catalog", schemaRevision: "app-store.catalog.v1",
    }, loader, {
      parentOrigin: "https://maverick.test",
      parentWindow: {
        postMessage(data: unknown, _origin: string, transfer?: Transferable[]) {
          subject.handleWindowMessage({ data, ports: transfer, origin: appOrigin, source: appWindow } as unknown as MessageEvent, new Set(["app-store"]));
        },
      } as Pick<Window, "postMessage">,
      sanitize: (payload) => payload as { revision: string; items: unknown[] },
    });
    let settled = false;
    void result.then(() => { settled = true; }, () => { settled = true; });
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(settled).toBe(false);
    expect(loader).toHaveBeenCalledTimes(1);
    expect(shellRetryCoordinator.pendingCount()).toBeGreaterThan(0);
    if (outcome === "cleanup") {
      const rejected = expect(result).rejects.toBeInstanceOf(Error);
      shellRetryCoordinator.cancelAll("PWA cache was cleared.");
      await rejected;
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(shellRetryCoordinator.pendingCount()).toBe(0);
    } else {
      await expect(result).resolves.toMatchObject({ brokered: true, source: "network", revision: "recovered" });
      expect(fetch).toHaveBeenCalledTimes(2);
    }
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("mediates a network miss and then returns a warm hit with conditional revalidation", async () => {
    vi.stubGlobal("navigator", {
      storage: { estimate: async () => ({ quota: 100_000_000, usage: 0 }) },
    });
    let finishConfig!: (enabled: boolean | null) => void;
    const slowConfig = new Promise<boolean | null>((resolve) => { finishConfig = resolve; });
    const feature = vi.fn<() => Promise<boolean | null>>().mockResolvedValueOnce(true).mockReturnValue(slowConfig);
    const subject = broker(feature);
    brokers.push(subject);
    const enabled = new Set(["app-store"]);

    const firstChannel = new MessageChannel();
    const firstMessages = portMessages(firstChannel.port1);
    expect(subject.handleWindowMessage(requestEvent(firstChannel), enabled)).toBe(true);
    await expect(firstMessages.next()).resolves.toMatchObject({ type: PWA_DATA_CACHE_BROKER_ACCEPTED });
    const network = await nextOfType(firstMessages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    expect(network.known_revision).toBeUndefined();
    firstChannel.port1.postMessage({
      app_id: "app-store",
      kind: "value",
      network_request_id: network.network_request_id,
      payload: { items: [], revision: "revision-one", schema: "maverick.app-store-catalog.v1" },
      request_id: "request-one",
      revision: "revision-one",
      status: "ok",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });
    await expect(nextOfType(firstMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      phase: "initial",
      revision: "revision-one",
      source: "network",
      status: "ok",
    });

    const warmChannel = new MessageChannel();
    const warmMessages = portMessages(warmChannel.port1);
    expect(subject.handleWindowMessage(requestEvent(warmChannel, { request_id: "request-two" }), enabled)).toBe(true);
    await nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    const initial = await nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_RESULT);
    expect(initial).toMatchObject({
      has_revalidation: true,
      phase: "initial",
      revision: "revision-one",
      source: "cache",
      status: "ok",
    });
    expect(feature).toHaveBeenCalledTimes(2);
    finishConfig(null); // Cache paint above did not await this config refresh.
    const revalidation = await nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    expect(revalidation.known_revision).toBe("revision-one");
    warmChannel.port1.postMessage({
      app_id: "app-store",
      kind: "not_modified",
      network_request_id: revalidation.network_request_id,
      request_id: "request-two",
      revision: "revision-one",
      status: "ok",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });
    await expect(nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      changed: false,
      phase: "revalidation",
      revision: "revision-one",
      status: "ok",
    });
  });

  it("applies a background rollout denial after a warm paint and never re-enables that broker", async () => {
    vi.stubGlobal("navigator", { storage: { estimate: async () => ({ quota: 100_000_000, usage: 0 }) } });
    let deny!: (value: boolean) => void;
    const refresh = new Promise<boolean>((resolve) => { deny = resolve; });
    const feature = vi.fn<() => Promise<boolean | null>>().mockResolvedValueOnce(true).mockReturnValue(refresh);
    const subject = broker(feature);
    brokers.push(subject);
    const enabled = new Set(["app-store"]);
    const seed = new MessageChannel();
    const seedMessages = portMessages(seed.port1);
    subject.handleWindowMessage(requestEvent(seed, {
      entity_id: "background-denial", request_id: "denial-seed",
      migration_seed: { payload: { revision: "one" }, revision: "one" },
    }), enabled);
    await nextOfType(seedMessages, PWA_DATA_CACHE_BROKER_RESULT);
    // A second warm request must not wait for the still-pending config refresh.
    const warm = new MessageChannel();
    const messages = portMessages(warm.port1);
    subject.handleWindowMessage(requestEvent(warm, { entity_id: "background-denial", request_id: "denial-warm" }), enabled);
    await expect(nextOfType(messages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({ source: "cache", status: "ok" });
    deny(false);
    await expect(nextOfType(messages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({ phase: "revalidation", status: "error" });
    const denied = new MessageChannel();
    const deniedMessages = portMessages(denied.port1);
    subject.handleWindowMessage(requestEvent(denied, { request_id: "denial-final" }), enabled);
    await expect(nextOfType(deniedMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({ status: "unavailable" });
    expect(feature).toHaveBeenCalledTimes(2);
  });

  it("never serves a new-workspace warm value to a frame from the previous workspace scope", async () => {
    vi.stubGlobal("navigator", {
      storage: { estimate: async () => ({ quota: 100_000_000, usage: 0 }) },
    });
    const enabled = new Set(["app-store"]);
    const entityId = `workspace-scope-${crypto.randomUUID()}`;
    const oldFrameScope = Object.freeze({
      sessionGeneration: "session-workspace-a",
      workspaceId: "workspace-a",
    });
    const previousWorkspaceBroker = broker(async () => true, oldFrameScope);
    brokers.push(previousWorkspaceBroker);
    previousWorkspaceBroker.dispose();
    const currentBroker = broker();
    brokers.push(currentBroker);

    const seedChannel = new MessageChannel();
    const seedMessages = portMessages(seedChannel.port1);
    currentBroker.handleWindowMessage(requestEvent(seedChannel, {
      entity_id: entityId,
      request_id: "request-scope-seed",
    }), enabled);
    await nextOfType(seedMessages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    const seedNetwork = await nextOfType(seedMessages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    seedChannel.port1.postMessage({
      app_id: "app-store",
      kind: "value",
      network_request_id: seedNetwork.network_request_id,
      payload: { items: [{ app_id: "private-b" }], revision: "workspace-b-revision", schema: "maverick.app-store-catalog.v1" },
      request_id: "request-scope-seed",
      revision: "workspace-b-revision",
      status: "ok",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });
    await expect(nextOfType(seedMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      source: "network",
      status: "ok",
    });

    const currentChannel = new MessageChannel();
    const currentMessages = portMessages(currentChannel.port1);
    currentBroker.handleWindowMessage(requestEvent(currentChannel, {
      entity_id: entityId,
      request_id: "request-current-workspace",
    }), enabled);
    await nextOfType(currentMessages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    await expect(nextOfType(currentMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      payload: { items: [{ app_id: "private-b" }] },
      source: "cache",
      status: "ok",
    });
    const revalidation = await nextOfType(currentMessages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    currentChannel.port1.postMessage({
      app_id: "app-store",
      kind: "not_modified",
      network_request_id: revalidation.network_request_id,
      request_id: "request-current-workspace",
      revision: "workspace-b-revision",
      status: "ok",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });
    await nextOfType(currentMessages, PWA_DATA_CACHE_BROKER_RESULT);

    const oldWindow = {} as Window;
    const oldOrigin = "https://af-old-app-store.sidecars.maverick.test";
    const oldFrame = { contentWindow: oldWindow, dataset: {} } as unknown as HTMLIFrameElement;
    const shellWindow = { location: { origin: "https://maverick.test" } } as unknown as Window;
    Object.assign(shellWindow, { top: shellWindow });
    vi.stubGlobal("window", shellWindow);
    registerFrame(oldFrame, oldOrigin, "app-store", oldFrameScope);
    const oldChannel = new MessageChannel();
    const oldMessages = portMessages(oldChannel.port1);
    expect(currentBroker.handleWindowMessage(requestEvent(oldChannel, {
      entity_id: entityId,
      request_id: "request-old-workspace",
    }, { origin: oldOrigin, source: oldWindow }), enabled)).toBe(true);
    await expect(oldMessages.next(100)).resolves.toMatchObject({
      type: PWA_DATA_CACHE_BROKER_ACCEPTED,
    });
    await expect(oldMessages.next(100)).resolves.toMatchObject({
      phase: "initial",
      status: "unavailable",
      type: PWA_DATA_CACHE_BROKER_RESULT,
    });
  });

  it("commits an app-sanitized legacy seed before allowing it to paint", async () => {
    vi.stubGlobal("navigator", {
      storage: { estimate: async () => ({ quota: 100_000_000, usage: 0 }) },
    });
    const subject = broker();
    brokers.push(subject);
    const channel = new MessageChannel();
    const messages = portMessages(channel.port1);
    const seed = {
      items: [],
      revision: "seed-revision",
      schema: "maverick.app-store-catalog.v1",
    };

    subject.handleWindowMessage(requestEvent(channel, {
      migration_seed: { payload: seed, revision: "seed-revision" },
      request_id: "request-migration",
    }), new Set(["app-store"]));

    await nextOfType(messages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    await expect(nextOfType(messages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      migration_committed: true,
      payload: seed,
      phase: "initial",
      source: "cache",
      status: "ok",
    });
    const revalidation = await nextOfType(messages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    expect(revalidation.known_revision).toBe("seed-revision");
    channel.port1.postMessage({
      app_id: "app-store",
      kind: "not_modified",
      network_request_id: revalidation.network_request_id,
      request_id: "request-migration",
      revision: "seed-revision",
      status: "ok",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });
    await expect(nextOfType(messages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      changed: false,
      phase: "revalidation",
    });
  });

  it("cleans and blocks the cache after an app network read returns 401", async () => {
    vi.stubGlobal("navigator", {
      storage: { estimate: async () => ({ quota: 100_000_000, usage: 0 }) },
    });
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockResolvedValue({
      pendingCleanupCount: 0,
      removed: 0,
      status: "complete",
    });
    const subject = broker();
    brokers.push(subject);
    const channel = new MessageChannel();
    const messages = portMessages(channel.port1);
    subject.handleWindowMessage(
      requestEvent(channel, { request_id: "request-auth" }),
      new Set(["app-store"]),
    );

    await nextOfType(messages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    const network = await nextOfType(messages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    channel.port1.postMessage({
      app_id: "app-store",
      error: { name: "MaverickHttpError", status: 401 },
      network_request_id: network.network_request_id,
      request_id: "request-auth",
      status: "error",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });

    await expect(nextOfType(messages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      phase: "initial",
      status: "error",
    });
    expect(cleanup).toHaveBeenCalledOnce();

    const blockedChannel = new MessageChannel();
    const blockedMessages = portMessages(blockedChannel.port1);
    subject.handleWindowMessage(
      requestEvent(blockedChannel, { request_id: "request-after-auth" }),
      new Set(["app-store"]),
    );
    await nextOfType(blockedMessages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    await expect(nextOfType(blockedMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      status: "unavailable",
    });
  });

  it("notifies the shell after a warm cached value revalidates with 403", async () => {
    vi.stubGlobal("navigator", {
      storage: { estimate: async () => ({ quota: 100_000_000, usage: 0 }) },
    });
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockResolvedValue({
      pendingCleanupCount: 0,
      removed: 1,
      status: "complete",
    });
    const authorizationFailure = vi.fn();
    authorizationSubscriptions.push(subscribeShellAuthorizationRevocation(authorizationFailure));
    const subject = broker();
    brokers.push(subject);
    const entityId = `warm-auth-${crypto.randomUUID()}`;

    const seedChannel = new MessageChannel();
    const seedMessages = portMessages(seedChannel.port1);
    subject.handleWindowMessage(requestEvent(seedChannel, {
      entity_id: entityId,
      request_id: "request-warm-auth-seed",
    }), new Set(["app-store"]));
    await nextOfType(seedMessages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    const seedNetwork = await nextOfType(seedMessages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    seedChannel.port1.postMessage({
      app_id: "app-store",
      kind: "value",
      network_request_id: seedNetwork.network_request_id,
      payload: { items: [], revision: "warm-revision", schema: "maverick.app-store-catalog.v1" },
      request_id: "request-warm-auth-seed",
      revision: "warm-revision",
      status: "ok",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });
    await expect(nextOfType(seedMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      source: "network",
      status: "ok",
    });

    const warmChannel = new MessageChannel();
    const warmMessages = portMessages(warmChannel.port1);
    subject.handleWindowMessage(requestEvent(warmChannel, {
      entity_id: entityId,
      request_id: "request-warm-auth-revalidation",
    }), new Set(["app-store"]));
    await nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    await expect(nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      has_revalidation: true,
      source: "cache",
      status: "ok",
    });
    const revalidation = await nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    warmChannel.port1.postMessage({
      app_id: "app-store",
      error: { name: "MaverickHttpError", status: 403 },
      network_request_id: revalidation.network_request_id,
      request_id: "request-warm-auth-revalidation",
      status: "error",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });

    await expect(nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      phase: "revalidation",
      status: "error",
    });
    expect(authorizationFailure).toHaveBeenCalledOnce();
    expect(authorizationFailure).toHaveBeenCalledWith(403);
    expect(cleanup).toHaveBeenCalledOnce();
  });

  it("answers and serves a Storage catalog read from a separately registered widget frame", async () => {
    const subject = broker();
    brokers.push(subject);
    const widgetWindow = {} as Window;
    const widgetOrigin = "https://af-storage-widget.sidecars.maverick.test";
    const widgetFrame = {
      contentWindow: widgetWindow,
      dataset: {},
    } as unknown as HTMLIFrameElement;
    const shellWindow = { location: { origin: "https://maverick.test" } } as unknown as Window;
    vi.stubGlobal("window", shellWindow);
    registerFrame(widgetFrame, widgetOrigin, "storage");
    vi.unstubAllGlobals();
    vi.stubGlobal("navigator", {
      storage: { estimate: async () => ({ quota: 100_000_000, usage: 0 }) },
    });
    const disabledChannel = new MessageChannel();
    const disabledMessages = portMessages(disabledChannel.port1);
    const disabledEvent = {
      data: {
        app_id: "storage",
        entity_id: "catalog:first-page",
        request_id: "request-storage-widget-disabled",
        resource: "file-catalog",
        schema_revision: "storage.file-catalog.v1",
        type: PWA_DATA_CACHE_BROKER_OPEN,
      },
      origin: widgetOrigin,
      ports: [disabledChannel.port2],
      source: widgetWindow,
    } as unknown as MessageEvent;
    expect(subject.handleWindowMessage(disabledEvent, new Set())).toBe(true);
    await expect(disabledMessages.next(100)).resolves.toMatchObject({
      app_id: "storage",
      type: PWA_DATA_CACHE_BROKER_ACCEPTED,
    });
    await expect(disabledMessages.next(100)).resolves.toMatchObject({
      status: "unavailable",
      type: PWA_DATA_CACHE_BROKER_RESULT,
    });

    const channel = new MessageChannel();
    const messages = portMessages(channel.port1);
    const event = {
      data: {
        app_id: "storage",
        entity_id: "catalog:first-page",
        request_id: "request-storage-widget",
        resource: "file-catalog",
        schema_revision: "storage.file-catalog.v1",
        type: PWA_DATA_CACHE_BROKER_OPEN,
      },
      origin: widgetOrigin,
      ports: [channel.port2],
      source: widgetWindow,
    } as unknown as MessageEvent;

    expect(subject.handleWindowMessage(event, new Set(["storage"]))).toBe(true);
    await expect(messages.next(100)).resolves.toMatchObject({
      app_id: "storage",
      type: PWA_DATA_CACHE_BROKER_ACCEPTED,
    });
    const network = await nextOfType(messages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    channel.port1.postMessage({
      app_id: "storage",
      kind: "value",
      network_request_id: network.network_request_id,
      payload: { files: [], folders: [], revision: "catalog-revision" },
      request_id: "request-storage-widget",
      revision: "catalog-revision",
      status: "ok",
      type: PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
    });
    await expect(nextOfType(messages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      source: "network",
      status: "ok",
    });
  });

  it("maps Storage metadata events to the declared catalog resource", async () => {
    const shellWindow = { location: { origin: "https://maverick.test" } } as unknown as Window;
    Object.assign(shellWindow, { top: shellWindow });
    vi.stubGlobal("window", shellWindow);
    const subject = broker();
    brokers.push(subject);
    const invalidation = vi.spyOn(shellCacheLifecycle, "handleDataChanged").mockResolvedValue({
      pendingCleanupCount: 0,
      removed: 1,
      status: "complete",
    });
    const storageWindow = {} as Window;
    const storageOrigin = "https://af-storage.sidecars.maverick.test";
    const storageFrame = {
      contentWindow: storageWindow,
      dataset: {},
    } as unknown as HTMLIFrameElement;
    registerFrame(storageFrame, storageOrigin, "storage");

    subject.handleDataChangedMessage({
      data: {
        owner_app_id: "storage",
        resource: "drive-connections",
        type: "maverick.app.data-changed",
      },
      origin: storageOrigin,
      source: storageWindow,
    } as MessageEvent);

    await vi.waitFor(() => expect(invalidation).toHaveBeenCalledWith({
      ownerAppId: "storage",
      resource: "file-catalog",
    }));
  });

  it("does not let a registered widget invalidate another app owner's cache", async () => {
    const shellWindow = { location: { origin: "https://maverick.test" } } as unknown as Window;
    Object.assign(shellWindow, { top: shellWindow });
    vi.stubGlobal("window", shellWindow);
    const subject = broker();
    brokers.push(subject);
    const invalidation = vi.spyOn(shellCacheLifecycle, "handleDataChanged").mockResolvedValue({
      pendingCleanupCount: 0,
      removed: 0,
      status: "complete",
    });
    const storageWindow = {} as Window;
    const storageOrigin = "https://af-storage-widget.sidecars.maverick.test";
    const storageFrame = {
      contentWindow: storageWindow,
      dataset: {},
    } as unknown as HTMLIFrameElement;
    registerFrame(storageFrame, storageOrigin, "storage");

    subject.handleDataChangedMessage({
      data: {
        owner_app_id: "website-studio",
        resource: "source",
        type: "maverick.app.data-changed",
      },
      origin: storageOrigin,
      source: storageWindow,
    } as MessageEvent);
    await Promise.resolve();

    expect(invalidation).not.toHaveBeenCalled();
  });

  it("cancels an accepted read before invalidating its resource", async () => {
    const shellWindow = new EventTarget() as EventTarget & Window;
    Object.assign(shellWindow, { location: { origin: "https://maverick.test" }, top: shellWindow });
    const invalidation = vi.spyOn(shellCacheLifecycle, "handleDataChanged").mockResolvedValue({
      pendingCleanupCount: 0,
      removed: 1,
      status: "complete",
    });
    const subject = broker();
    brokers.push(subject);
    const channel = new MessageChannel();
    const entityId = `invalidated-${crypto.randomUUID()}`;
    const messages = portMessages(channel.port1);
    subject.handleWindowMessage(
      requestEvent(channel, { entity_id: entityId, request_id: "request-invalidated" }),
      new Set(["app-store"]),
    );
    await expect(messages.next()).resolves.toMatchObject({ type: PWA_DATA_CACHE_BROKER_ACCEPTED });
    await nextOfType(messages, PWA_DATA_CACHE_BROKER_NETWORK_REQUEST);
    expect((subject as unknown as { active: Map<string, unknown> }).active.size).toBe(1);
    vi.stubGlobal("window", shellWindow);
    subject.handleDataChangedMessage({
      data: {
        entity_id: entityId,
        owner_app_id: "app-store",
        resource: "catalog",
        type: "maverick.app.data-changed",
      },
      origin: shellWindow.location.origin,
      source: shellWindow,
    } as MessageEvent);

    expect((subject as unknown as { active: Map<string, unknown> }).active.size).toBe(0);
    await vi.waitFor(() => expect(invalidation).toHaveBeenCalledWith({
      entityId,
      ownerAppId: "app-store",
      resource: "catalog",
    }));
    await expect(messages.next()).resolves.toMatchObject({
      phase: "initial",
      status: "unavailable",
      type: PWA_DATA_CACHE_BROKER_RESULT,
    });
  });

  it("answers unavailable immediately when either rollout gate is closed", async () => {
    const perAppDisabled = broker();
    brokers.push(perAppDisabled);
    const perAppChannel = new MessageChannel();
    const perAppMessages = portMessages(perAppChannel.port1);

    expect(perAppDisabled.handleWindowMessage(
      requestEvent(perAppChannel),
      new Set(),
    )).toBe(true);
    await expect(perAppMessages.next()).resolves.toMatchObject({
      type: PWA_DATA_CACHE_BROKER_ACCEPTED,
    });
    await expect(nextOfType(perAppMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      phase: "initial",
      status: "unavailable",
    });

    const globalDisabled = broker(async () => false);
    brokers.push(globalDisabled);
    const globalChannel = new MessageChannel();
    const globalMessages = portMessages(globalChannel.port1);
    globalDisabled.handleWindowMessage(
      requestEvent(globalChannel, { request_id: "request-global" }),
      new Set(["app-store"]),
    );
    await expect(nextOfType(globalMessages, PWA_DATA_CACHE_BROKER_ACCEPTED)).resolves.toBeTruthy();
    await expect(nextOfType(globalMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      phase: "initial",
      status: "unavailable",
    });
  });

  it("fails closed for unknown schemas without leaving the transferred port pending", async () => {
    const subject = broker();
    brokers.push(subject);
    const channel = new MessageChannel();
    const messages = portMessages(channel.port1);

    expect(subject.handleWindowMessage(
      requestEvent(channel, { resource: "control-plane" }),
      new Set(["app-store"]),
    )).toBe(true);

    await expect(nextOfType(messages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      phase: "initial",
      status: "unavailable",
    });
  });

  it("rejects the same request when it is not from the registered exact-origin frame", () => {
    const subject = broker();
    brokers.push(subject);
    const channel = new MessageChannel();

    expect(subject.handleWindowMessage(
      { ...requestEvent(channel), source: {} as Window } as MessageEvent,
      new Set(["app-store"]),
    )).toBe(false);
  });
});
