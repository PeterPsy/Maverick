import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PWA_DATA_CACHE_BROKER_ACCEPTED,
  PWA_DATA_CACHE_BROKER_NETWORK_REQUEST,
  PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
  PWA_DATA_CACHE_BROKER_OPEN,
  PWA_DATA_CACHE_BROKER_RESULT,
} from "@maverick/pwa-cache";
import { PwaDataCacheBroker } from "./pwaDataCacheBroker";
import { shellCacheLifecycle } from "./pwaCacheRuntime";

type PortMessage = Record<string, unknown>;

const appWindow = {} as Window;
const appOrigin = "https://af-app-store.sidecars.maverick.test";
const appFrame = {
  contentWindow: appWindow,
  dataset: { maverickFrameOrigin: appOrigin },
} as unknown as HTMLIFrameElement;

function requestEvent(channel: MessageChannel, overrides: Record<string, unknown> = {}): MessageEvent {
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
    origin: appOrigin,
    ports: [channel.port2],
    source: appWindow,
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

function broker(featureEnabled: () => Promise<boolean | null> = async () => true): PwaDataCacheBroker {
  return new PwaDataCacheBroker({
    featureEnabled,
    principal: { userId: "user-one", workspaceId: "default" },
  });
}

describe("Base Shell structured data-cache broker", () => {
  const brokers: PwaDataCacheBroker[] = [];

  afterEach(() => {
    brokers.splice(0).forEach((item) => item.dispose());
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("mediates a network miss and then returns a warm hit with conditional revalidation", async () => {
    vi.stubGlobal("navigator", {
      storage: { estimate: async () => ({ quota: 100_000_000, usage: 0 }) },
    });
    const subject = broker();
    brokers.push(subject);
    const frames = { "app-store": appFrame };
    const enabled = new Set(["app-store"]);

    const firstChannel = new MessageChannel();
    const firstMessages = portMessages(firstChannel.port1);
    expect(subject.handleWindowMessage(requestEvent(firstChannel), frames, enabled)).toBe(true);
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
    expect(subject.handleWindowMessage(requestEvent(warmChannel, { request_id: "request-two" }), frames, enabled)).toBe(true);
    await nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    const initial = await nextOfType(warmMessages, PWA_DATA_CACHE_BROKER_RESULT);
    expect(initial).toMatchObject({
      has_revalidation: true,
      phase: "initial",
      revision: "revision-one",
      source: "cache",
      status: "ok",
    });
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
    }), { "app-store": appFrame }, new Set(["app-store"]));

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
    subject.handleWindowMessage(requestEvent(channel, { request_id: "request-auth" }), {
      "app-store": appFrame,
    }, new Set(["app-store"]));

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
    subject.handleWindowMessage(requestEvent(blockedChannel, { request_id: "request-after-auth" }), {
      "app-store": appFrame,
    }, new Set(["app-store"]));
    await nextOfType(blockedMessages, PWA_DATA_CACHE_BROKER_ACCEPTED);
    await expect(nextOfType(blockedMessages, PWA_DATA_CACHE_BROKER_RESULT)).resolves.toMatchObject({
      status: "unavailable",
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
      dataset: { maverickFrameOrigin: storageOrigin },
    } as unknown as HTMLIFrameElement;

    subject.handleDataChangedMessage({
      data: {
        owner_app_id: "storage",
        resource: "drive-connections",
        type: "maverick.app.data-changed",
      },
      origin: storageOrigin,
      source: storageWindow,
    } as MessageEvent, { storage: storageFrame });

    await vi.waitFor(() => expect(invalidation).toHaveBeenCalledWith({
      ownerAppId: "storage",
      resource: "file-catalog",
    }));
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
      { "app-store": appFrame },
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
    } as MessageEvent, { "app-store": appFrame });

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
      { "app-store": appFrame },
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
      { "app-store": appFrame },
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
      { "app-store": appFrame },
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
      { "app-store": appFrame },
      new Set(["app-store"]),
    )).toBe(false);
  });
});
