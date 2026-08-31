import { describe, expect, it, vi } from "vitest";
import {
  PWA_FILE_CACHE_BROKER_OPEN,
  requestParentFileCacheOpen,
} from "../src";

function parentThat(
  handler: (message: Record<string, unknown>, port: MessagePort) => void,
): Pick<Window, "postMessage"> {
  return {
    postMessage: vi.fn((message: unknown, _targetOrigin: string, transfer?: Transferable[]) => {
      handler(message as Record<string, unknown>, transfer?.[0] as MessagePort);
    }) as unknown as Window["postMessage"],
  };
}

describe("parent-mediated file-cache protocol", () => {
  it("returns a brokered blob only after the parent accepts the request", async () => {
    const parent = parentThat((message, port) => {
      expect(message).toMatchObject({
        app_id: "storage",
        file_id: "file-one",
        source_version: "version-one",
        type: PWA_FILE_CACHE_BROKER_OPEN,
      });
      port.postMessage({
        app_id: "storage",
        request_id: message.request_id,
        type: "maverick.storage.file-cache.accepted.v1",
      });
      port.postMessage({
        app_id: "storage",
        blob: new Blob(["cached"], { type: "text/plain" }),
        request_id: message.request_id,
        source: "cache",
        status: "ok",
        type: "maverick.storage.file-cache.result.v1",
      });
    });

    const result = await requestParentFileCacheOpen({
      fileId: "file-one",
      sourceVersion: "version-one",
    }, {
      parentOrigin: "https://maverick.test",
      parentWindow: parent,
    });

    expect(result?.source).toBe("cache");
    expect(await result?.blob.text()).toBe("cached");
  });

  it("returns null when the broker is disabled or the handshake is absent", async () => {
    const unavailableParent = parentThat((message, port) => {
      port.postMessage({
        app_id: "storage",
        request_id: message.request_id,
        type: "maverick.storage.file-cache.accepted.v1",
      });
      port.postMessage({
        app_id: "storage",
        request_id: message.request_id,
        status: "unavailable",
        type: "maverick.storage.file-cache.result.v1",
      });
    });
    await expect(requestParentFileCacheOpen({
      fileId: "file-one",
      sourceVersion: "version-one",
    }, { parentWindow: unavailableParent })).resolves.toBeNull();

    const silentParent = parentThat(() => undefined);
    await expect(requestParentFileCacheOpen({
      fileId: "file-one",
      sourceVersion: "version-one",
    }, {
      acceptanceTimeoutMs: 5,
      parentWindow: silentParent,
    })).resolves.toBeNull();
  });

  it("cancels pending work over the private message port", async () => {
    const controller = new AbortController();
    const cancel = vi.fn();
    const parent = parentThat((message, port) => {
      port.addEventListener("message", (event) => {
        if (event.data?.type === "maverick.storage.file-cache.cancel.v1") cancel();
      });
      port.start();
      port.postMessage({
        app_id: "storage",
        request_id: message.request_id,
        type: "maverick.storage.file-cache.accepted.v1",
      });
      controller.abort();
    });

    await expect(requestParentFileCacheOpen({
      fileId: "file-one",
      sourceVersion: "version-one",
    }, {
      parentWindow: parent,
      signal: controller.signal,
    })).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(cancel).toHaveBeenCalledOnce());
  });
});
