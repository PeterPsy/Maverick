import { describe, expect, it, vi } from "vitest";
import {
  PWA_FILE_CACHE_BROKER_ACCEPTED,
  PWA_FILE_CACHE_BROKER_OPEN,
  PWA_FILE_CACHE_BROKER_RESULT,
} from "@maverick/pwa-cache";
import { StorageFileCacheBroker } from "./storageFileCacheBroker";

const storageWindow = {} as Window;

function requestEvent(
  channel: MessageChannel,
  overrides: Record<string, unknown> = {},
): MessageEvent {
  return {
    data: {
      app_id: "storage",
      file_id: "file-one",
      request_id: "request-one",
      source_version: "version-one",
      type: PWA_FILE_CACHE_BROKER_OPEN,
      ...overrides,
    },
    origin: "https://maverick.test",
    ports: [channel.port2],
    source: storageWindow,
  } as unknown as MessageEvent;
}

function approvedDescriptor(overrides: Record<string, unknown> = {}) {
  return {
    schema: "maverick.storage-file-cache-descriptor.v1",
    eligible: true,
    reason_code: "approved",
    policy: {
      policy_revision: "maverick.local-persistence-policy.v2",
      data_class: "workspace_internal",
      provenance: "attachment",
      cache_approved: true,
      privacy_approved: false,
      regulated_allowlisted: false,
    },
    file: {
      file_id: "file-one",
      source_version: "version-one",
      size_bytes: 6,
      content_type: "text/plain",
      expected_sha256: "",
      media_url: "/api/apps/storage/media?stable_storage_file_id=file-one&source_version=version-one&download=1&_pwa_file_cache=1",
    },
    ...overrides,
  };
}

function nextPortMessage(port: MessagePort): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    port.addEventListener("message", (event) => resolve(event.data), { once: true });
    port.start();
  });
}

describe("Base Shell Storage file-cache broker", () => {
  it("accepts only the mounted Storage frame and returns normal file bytes", async () => {
    const openFile = vi.fn(async () => ({
      blob: new Blob(["cached"]),
      etag: '"one"',
      source: "cache" as const,
    }));
    const broker = new StorageFileCacheBroker({
      featureEnabled: async () => true,
      hostOrigin: "https://maverick.test",
      openFile,
      principal: { appId: "storage", userId: "user-one", workspaceId: "default" },
      resolveDescriptor: async () => approvedDescriptor(),
    });
    const channel = new MessageChannel();
    const accepted = nextPortMessage(channel.port1);

    expect(broker.handleWindowMessage(requestEvent(channel), storageWindow)).toBe(true);
    await expect(accepted).resolves.toMatchObject({
      request_id: "request-one",
      type: PWA_FILE_CACHE_BROKER_ACCEPTED,
    });
    await expect(nextPortMessage(channel.port1)).resolves.toMatchObject({
      request_id: "request-one",
      source: "cache",
      status: "ok",
      type: PWA_FILE_CACHE_BROKER_RESULT,
    });
    expect(openFile).toHaveBeenCalledWith(expect.objectContaining({
      descriptor: expect.objectContaining({ fileId: "file-one", sourceVersion: "version-one" }),
      url: "/api/apps/storage/media?stable_storage_file_id=file-one&source_version=version-one&download=1&_pwa_file_cache=1",
    }), expect.any(AbortSignal));

    const foreignChannel = new MessageChannel();
    expect(broker.handleWindowMessage(requestEvent(foreignChannel), {} as Window)).toBe(false);
    broker.dispose();
  });

  it("fails closed to ordinary network handling for disabled, denied, or malformed policy", async () => {
    const openFile = vi.fn();
    const denied = new StorageFileCacheBroker({
      featureEnabled: async () => true,
      hostOrigin: "https://maverick.test",
      openFile,
      principal: { appId: "storage", userId: "user-one", workspaceId: "default" },
      resolveDescriptor: async () => ({ ...approvedDescriptor(), eligible: false, reason_code: "unclassified" }),
    });
    const deniedChannel = new MessageChannel();
    const accepted = nextPortMessage(deniedChannel.port1);
    denied.handleWindowMessage(requestEvent(deniedChannel), storageWindow);
    await accepted;
    await expect(nextPortMessage(deniedChannel.port1)).resolves.toMatchObject({ status: "unavailable" });
    expect(openFile).not.toHaveBeenCalled();
    denied.dispose();

    const malformed = new StorageFileCacheBroker({
      featureEnabled: async () => true,
      hostOrigin: "https://maverick.test",
      openFile,
      principal: { appId: "storage", userId: "user-one", workspaceId: "default" },
      resolveDescriptor: async () => approvedDescriptor({
        file: { ...approvedDescriptor().file, media_url: "https://attacker.test/file" },
      }),
    });
    const malformedChannel = new MessageChannel();
    const malformedAccepted = nextPortMessage(malformedChannel.port1);
    malformed.handleWindowMessage(requestEvent(malformedChannel), storageWindow);
    await malformedAccepted;
    await expect(nextPortMessage(malformedChannel.port1)).resolves.toMatchObject({ status: "unavailable" });
    expect(openFile).not.toHaveBeenCalled();
    malformed.dispose();
  });

  it("aborts parent work when the private port sends cancellation", async () => {
    let operationSignal: AbortSignal | null = null;
    const broker = new StorageFileCacheBroker({
      featureEnabled: async () => true,
      hostOrigin: "https://maverick.test",
      openFile: async (_request, signal) => {
        operationSignal = signal;
        await new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason), { once: true }));
        throw new Error("unreachable");
      },
      principal: { appId: "storage", userId: "user-one", workspaceId: "default" },
      resolveDescriptor: async () => approvedDescriptor(),
    });
    const channel = new MessageChannel();
    const accepted = nextPortMessage(channel.port1);
    broker.handleWindowMessage(requestEvent(channel), storageWindow);
    await accepted;
    await vi.waitFor(() => expect(operationSignal).not.toBeNull());

    channel.port1.postMessage({ request_id: "request-one", type: "maverick.storage.file-cache.cancel.v1" });

    await vi.waitFor(() => expect(operationSignal?.aborted).toBe(true));
    broker.dispose();
  });

  it("does not return bytes that fail the trusted size or digest contract", async () => {
    const broker = new StorageFileCacheBroker({
      featureEnabled: async () => true,
      hostOrigin: "https://maverick.test",
      openFile: async () => ({ blob: new Blob(["wrong!"]), etag: '"one"', source: "network" }),
      principal: { appId: "storage", userId: "user-one", workspaceId: "default" },
      resolveDescriptor: async () => approvedDescriptor({
        file: { ...approvedDescriptor().file, expected_sha256: "0".repeat(64) },
      }),
    });
    const channel = new MessageChannel();
    const accepted = nextPortMessage(channel.port1);
    broker.handleWindowMessage(requestEvent(channel), storageWindow);
    await accepted;

    await expect(nextPortMessage(channel.port1)).resolves.toMatchObject({ status: "error" });
    broker.dispose();
  });

  it("rechecks explicit gate decisions while preserving a confirmed hit path across transport loss", async () => {
    const featureEnabled = vi.fn()
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(false);
    const resolveDescriptor = vi.fn(async () => approvedDescriptor());
    const openFile = vi.fn(async () => ({
      blob: new Blob(["cached"]),
      etag: '"one"',
      source: "cache" as const,
    }));
    const broker = new StorageFileCacheBroker({
      featureEnabled,
      hostOrigin: "https://maverick.test",
      openFile,
      principal: { appId: "storage", userId: "user-one", workspaceId: "default" },
      resolveDescriptor,
    });

    const coldTransportLossChannel = new MessageChannel();
    const coldTransportLossAccepted = nextPortMessage(coldTransportLossChannel.port1);
    broker.handleWindowMessage(requestEvent(coldTransportLossChannel, { request_id: "request-cold" }), storageWindow);
    await coldTransportLossAccepted;
    await expect(nextPortMessage(coldTransportLossChannel.port1)).resolves.toMatchObject({ status: "unavailable" });

    const enabledChannel = new MessageChannel();
    const enabledAccepted = nextPortMessage(enabledChannel.port1);
    broker.handleWindowMessage(requestEvent(enabledChannel), storageWindow);
    await enabledAccepted;
    await expect(nextPortMessage(enabledChannel.port1)).resolves.toMatchObject({ status: "ok" });

    const transportLossChannel = new MessageChannel();
    const transportLossAccepted = nextPortMessage(transportLossChannel.port1);
    broker.handleWindowMessage(requestEvent(transportLossChannel, { request_id: "request-two" }), storageWindow);
    await transportLossAccepted;
    await expect(nextPortMessage(transportLossChannel.port1)).resolves.toMatchObject({ status: "ok" });

    const disabledChannel = new MessageChannel();
    const disabledAccepted = nextPortMessage(disabledChannel.port1);
    broker.handleWindowMessage(requestEvent(disabledChannel, { request_id: "request-three" }), storageWindow);
    await disabledAccepted;
    await expect(nextPortMessage(disabledChannel.port1)).resolves.toMatchObject({ status: "unavailable" });

    expect(featureEnabled).toHaveBeenCalledTimes(4);
    expect(resolveDescriptor).toHaveBeenCalledTimes(1);
    expect(openFile).toHaveBeenCalledTimes(2);
    broker.dispose();
  });

  it("does not reuse a session descriptor after an explicit policy denial", async () => {
    const resolveDescriptor = vi.fn()
      .mockResolvedValueOnce(approvedDescriptor())
      .mockResolvedValueOnce({ ...approvedDescriptor(), eligible: false, reason_code: "unclassified" });
    const openFile = vi.fn(async () => ({
      blob: new Blob(["cached"]),
      etag: '"one"',
      source: "cache" as const,
    }));
    const broker = new StorageFileCacheBroker({
      featureEnabled: async () => true,
      hostOrigin: "https://maverick.test",
      openFile,
      principal: { appId: "storage", userId: "user-one", workspaceId: "default" },
      resolveDescriptor,
    });

    const approvedChannel = new MessageChannel();
    const approvedAccepted = nextPortMessage(approvedChannel.port1);
    broker.handleWindowMessage(requestEvent(approvedChannel), storageWindow);
    await approvedAccepted;
    await expect(nextPortMessage(approvedChannel.port1)).resolves.toMatchObject({ status: "ok" });

    const deniedChannel = new MessageChannel();
    const deniedAccepted = nextPortMessage(deniedChannel.port1);
    broker.handleWindowMessage(requestEvent(deniedChannel, { request_id: "request-denied" }), storageWindow);
    await deniedAccepted;
    await expect(nextPortMessage(deniedChannel.port1)).resolves.toMatchObject({ status: "unavailable" });

    expect(openFile).toHaveBeenCalledTimes(1);
    broker.dispose();
  });
});
