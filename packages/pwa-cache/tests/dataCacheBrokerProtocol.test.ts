import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PWA_DATA_CACHE_BROKER_ACCEPTED,
  PWA_DATA_CACHE_BROKER_INVALIDATE,
  PWA_DATA_CACHE_BROKER_NETWORK_REQUEST,
  PWA_DATA_CACHE_BROKER_NETWORK_RESULT,
  PWA_DATA_CACHE_BROKER_OPEN,
  PWA_DATA_CACHE_BROKER_RESULT,
  isExactMaverickParentMessage,
  readThroughParentDataCache,
  serializeParentDataCacheError,
} from "../src";

type Message = Record<string, unknown>;

function parentThat(
  handler: (message: Message, port: MessagePort) => void,
): Pick<Window, "postMessage"> {
  return {
    postMessage: vi.fn((message: unknown, _origin: string, transfer?: Transferable[]) => {
      handler(message as Message, transfer?.[0] as MessagePort);
    }) as unknown as Window["postMessage"],
  };
}

function postAccepted(message: Message, port: MessagePort): void {
  port.postMessage({
    app_id: message.app_id,
    request_id: message.request_id,
    type: PWA_DATA_CACHE_BROKER_ACCEPTED,
  });
}

function nextPortMessage(port: MessagePort): Promise<Message> {
  return new Promise((resolve) => {
    port.addEventListener("message", (event) => resolve(event.data), { once: true });
    port.start();
  });
}

const request = {
  appId: "app-store",
  entityId: "visible-catalog",
  resource: "catalog",
  schemaRevision: "app-store.catalog.v1",
};

function sanitize(value: unknown): { value: string } | null {
  const candidate = value as { value?: unknown } | null;
  return candidate && typeof candidate.value === "string" ? { value: candidate.value } : null;
}

describe("parent-mediated data-cache protocol", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("falls back to one ordinary server read when the parent broker is unavailable", async () => {
    const loader = vi.fn(async () => ({
      kind: "value" as const,
      payload: { value: "network" },
      revision: "revision-one",
    }));
    const parent = parentThat((message, port) => {
      expect(message).toMatchObject({
        app_id: "app-store",
        entity_id: "visible-catalog",
        resource: "catalog",
        schema_revision: "app-store.catalog.v1",
        type: PWA_DATA_CACHE_BROKER_OPEN,
      });
      postAccepted(message, port);
      port.postMessage({
        app_id: message.app_id,
        phase: "initial",
        request_id: message.request_id,
        status: "unavailable",
        type: PWA_DATA_CACHE_BROKER_RESULT,
      });
    });

    const result = await readThroughParentDataCache(request, loader, {
      parentOrigin: "https://maverick.test",
      parentWindow: parent,
      sanitize,
    });

    expect(result).toMatchObject({
      brokered: false,
      payload: { value: "network" },
      source: "network",
    });
    expect(loader).toHaveBeenCalledOnce();
  });

  it("recognizes shell events only from the exact injected parent origin", () => {
    const parent = {} as Window;
    const frameWindow = {
      __MAVERICK_PLATFORM_ORIGIN__: "https://maverick.test",
      location: { origin: "https://af-storage.sidecars.maverick.test" },
      parent,
    } as unknown as Window & { __MAVERICK_PLATFORM_ORIGIN__: string };
    vi.stubGlobal("window", frameWindow);

    expect(isExactMaverickParentMessage({
      origin: "https://maverick.test",
      source: parent,
    } as MessageEvent)).toBe(true);
    expect(isExactMaverickParentMessage({
      origin: frameWindow.location.origin,
      source: parent,
    } as MessageEvent)).toBe(false);
    expect(isExactMaverickParentMessage({
      origin: "https://maverick.test",
      source: {} as Window,
    } as MessageEvent)).toBe(false);
  });

  it("serves a cache hit first and carries conditional revalidation over the private port", async () => {
    const loader = vi.fn(async (context: { knownRevision?: string }) => {
      expect(context.knownRevision).toBe("revision-one");
      return { kind: "value" as const, payload: { value: "updated" }, revision: "revision-two" };
    });
    const parent = parentThat((message, port) => {
      port.addEventListener("message", (event) => {
        const reply = event.data as Message;
        if (reply.type !== PWA_DATA_CACHE_BROKER_NETWORK_RESULT) return;
        expect(reply).toMatchObject({
          app_id: "app-store",
          kind: "value",
          payload: { value: "updated" },
          revision: "revision-two",
          status: "ok",
        });
        port.postMessage({
          app_id: message.app_id,
          changed: true,
          payload: reply.payload,
          phase: "revalidation",
          request_id: message.request_id,
          revision: reply.revision,
          status: "ok",
          type: PWA_DATA_CACHE_BROKER_RESULT,
        });
      });
      port.start();
      postAccepted(message, port);
      port.postMessage({
        app_id: message.app_id,
        freshness: "fresh",
        has_revalidation: true,
        payload: { value: "cached" },
        phase: "initial",
        request_id: message.request_id,
        revision: "revision-one",
        source: "cache",
        status: "ok",
        type: PWA_DATA_CACHE_BROKER_RESULT,
      });
      port.postMessage({
        app_id: message.app_id,
        known_revision: "revision-one",
        network_request_id: "network-one",
        request_id: message.request_id,
        type: PWA_DATA_CACHE_BROKER_NETWORK_REQUEST,
      });
    });

    const result = await readThroughParentDataCache(request, loader, {
      parentOrigin: "https://maverick.test",
      parentWindow: parent,
      sanitize,
    });

    expect(result).toMatchObject({ brokered: true, payload: { value: "cached" }, source: "cache" });
    await expect(result.revalidation).resolves.toEqual({
      changed: true,
      payload: { value: "updated" },
      revision: "revision-two",
    });
    expect(loader).toHaveBeenCalledOnce();
  });

  it("invalidates an app-schema-invalid hit before falling back to the server", async () => {
    let invalidation: Promise<Message> | null = null;
    const parent = parentThat((message, port) => {
      invalidation = nextPortMessage(port);
      postAccepted(message, port);
      port.postMessage({
        app_id: message.app_id,
        freshness: "fresh",
        payload: { unexpected: true },
        phase: "initial",
        request_id: message.request_id,
        revision: "revision-bad",
        source: "cache",
        status: "ok",
        type: PWA_DATA_CACHE_BROKER_RESULT,
      });
    });

    const result = await readThroughParentDataCache(request, async () => ({
      kind: "value",
      payload: { value: "network" },
      revision: "revision-good",
    }), {
      parentOrigin: "https://maverick.test",
      parentWindow: parent,
      sanitize,
    });

    expect(result.brokered).toBe(false);
    await expect(invalidation).resolves.toMatchObject({ type: PWA_DATA_CACHE_BROKER_INVALIDATE });
  });

  it("cancels accepted parent work when the caller is aborted", async () => {
    const controller = new AbortController();
    let cancellation: Promise<Message> | null = null;
    const parent = parentThat((message, port) => {
      cancellation = nextPortMessage(port);
      postAccepted(message, port);
      controller.abort(new DOMException("unmounted", "AbortError"));
    });

    await expect(readThroughParentDataCache(request, async () => ({
      kind: "value",
      payload: { value: "unused" },
      revision: "unused",
    }), {
      parentOrigin: "https://maverick.test",
      parentWindow: parent,
      sanitize,
      signal: controller.signal,
    })).rejects.toMatchObject({ name: "AbortError" });

    await expect(cancellation).resolves.toMatchObject({ type: "maverick.pwa.data-cache.cancel.v1" });
  });

  it("preserves bounded auth and retry metadata without serializing error text", () => {
    const error = Object.assign(new Error("secret server detail"), {
      name: "MaverickHttpError",
      retryAfterMs: 120_000,
      status: 403,
    });

    expect(serializeParentDataCacheError(error)).toEqual({
      name: "MaverickHttpError",
      retry_after_ms: 60_000,
      status: 403,
    });
  });
});
