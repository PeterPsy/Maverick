import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PWA_CACHE_OPERATIONS_ACCEPTED,
  PWA_CACHE_OPERATIONS_REQUEST,
  PWA_CACHE_OPERATIONS_RESULT,
  createPwaCacheMetricsCollector,
} from "@maverick/pwa-cache";
import { setMaverickFrameOrigin } from "./iframePolicy";
import { PwaCacheOperationsBroker } from "./pwaCacheOperationsBroker";

const FRAME_SCOPE = Object.freeze({ sessionGeneration: "session-default", workspaceId: "default" });
const settingsWindow = {} as Window;
const settingsOrigin = "https://af-settings.sidecars.maverick.test";
const settingsFrame = { contentWindow: settingsWindow, dataset: {} } as unknown as HTMLIFrameElement;

function requestEvent(
  channel: MessageChannel,
  action: "clear" | "diagnostics" = "diagnostics",
  requestId = `request-${action}`,
): MessageEvent {
  return {
    data: {
      action,
      app_id: "settings",
      request_id: requestId,
      type: PWA_CACHE_OPERATIONS_REQUEST,
    },
    origin: settingsOrigin,
    ports: [channel.port2],
    source: settingsWindow,
  } as unknown as MessageEvent;
}

function nextMessage(port: MessagePort): Promise<Record<string, unknown>> {
  port.start();
  return new Promise((resolve, reject) => {
    const timeout = globalThis.setTimeout(() => reject(new Error("Timed out waiting for cache broker.")), 1_000);
    port.addEventListener("message", (event) => {
      globalThis.clearTimeout(timeout);
      resolve(event.data);
    }, { once: true });
  });
}

describe("Base Shell PWA cache operations broker", () => {
  beforeEach(() => {
    const shellWindow = new EventTarget() as EventTarget & Window;
    Object.assign(shellWindow, { location: { origin: "https://maverick.test" }, top: shellWindow });
    vi.stubGlobal("window", shellWindow);
    setMaverickFrameOrigin(settingsFrame, settingsOrigin, "settings", FRAME_SCOPE);
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    const shellWindow = new EventTarget() as EventTarget & Window;
    Object.assign(shellWindow, { location: { origin: "https://maverick.test" }, top: shellWindow });
    vi.stubGlobal("window", shellWindow);
    setMaverickFrameOrigin(settingsFrame, null, "settings", FRAME_SCOPE);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns only aggregate shell-origin diagnostics to the exact Settings frame", async () => {
    const metrics = createPwaCacheMetricsCollector({ now: () => 1_000, storage: null });
    metrics.recordDataCache({ bytes: 12, kind: "hit" });
    const lifecycle = {
      clearAll: vi.fn(),
      diagnostics: vi.fn(async () => diagnostics()),
    };
    const broker = new PwaCacheOperationsBroker({ frameScope: FRAME_SCOPE, lifecycle, metrics });
    const channel = new MessageChannel();

    expect(broker.handleWindowMessage(requestEvent(channel))).toBe(true);
    await expect(nextMessage(channel.port1)).resolves.toMatchObject({ type: PWA_CACHE_OPERATIONS_ACCEPTED });
    await expect(nextMessage(channel.port1)).resolves.toMatchObject({
      dashboard: {
        diagnostics: { cacheBytes: 12 },
        metrics: { counters: { pwa_data_cache_hit: 1 } },
      },
      status: "ok",
      type: PWA_CACHE_OPERATIONS_RESULT,
    });
    expect(lifecycle.clearAll).not.toHaveBeenCalled();
  });

  it("clears durable caches, pending retries, and aggregate metrics through one operation", async () => {
    const metrics = createPwaCacheMetricsCollector({ now: () => 1_000, storage: null });
    metrics.recordFileCache({ bytes: 10, count: 1, kind: "evict" });
    const lifecycle = {
      clearAll: vi.fn(async () => ({ pendingCleanupCount: 0, removed: 3, status: "complete" as const })),
      diagnostics: vi.fn(async () => diagnostics({ cacheBytes: 0, entryCount: 0 })),
    };
    const broker = new PwaCacheOperationsBroker({ frameScope: FRAME_SCOPE, lifecycle, metrics });
    const channel = new MessageChannel();

    broker.handleWindowMessage(requestEvent(channel, "clear"));
    await nextMessage(channel.port1);
    await expect(nextMessage(channel.port1)).resolves.toMatchObject({
      cleanup: { removed: 3, status: "complete" },
      dashboard: { metrics: { counters: { pwa_eviction_count: 0 } } },
      status: "ok",
    });
    expect(lifecycle.clearAll).toHaveBeenCalledOnce();
  });

  it("does not accept the protocol from an unregistered source", () => {
    const broker = new PwaCacheOperationsBroker({ frameScope: FRAME_SCOPE });
    const channel = new MessageChannel();
    const event = requestEvent(channel);
    Object.defineProperty(event, "source", { value: {} as Window });

    expect(broker.handleWindowMessage(event)).toBe(false);
    channel.port1.close();
    channel.port2.close();
  });

  it("retains incident metrics when durable cleanup remains pending", async () => {
    const metrics = createPwaCacheMetricsCollector({ now: () => 1_000, storage: null });
    metrics.recordDataCache({ kind: "error", reason: "redacted" });
    const lifecycle = {
      clearAll: vi.fn(async () => ({ pendingCleanupCount: 1, removed: 0, status: "pending" as const })),
      diagnostics: vi.fn(async () => diagnostics()),
    };
    const broker = new PwaCacheOperationsBroker({ frameScope: FRAME_SCOPE, lifecycle, metrics });
    const channel = new MessageChannel();

    broker.handleWindowMessage(requestEvent(channel, "clear"));
    await nextMessage(channel.port1);
    await expect(nextMessage(channel.port1)).resolves.toMatchObject({
      cleanup: { pendingCleanupCount: 1, status: "pending" },
      dashboard: { metrics: { counters: { pwa_revalidate_error: 1 } } },
    });
  });

  it("bounds concurrent diagnostics from a compromised Settings frame", async () => {
    const lifecycle = {
      clearAll: vi.fn(),
      diagnostics: vi.fn(() => new Promise<ReturnType<typeof diagnostics>>(() => undefined)),
    };
    const broker = new PwaCacheOperationsBroker({ frameScope: FRAME_SCOPE, lifecycle });
    const channels = Array.from({ length: 9 }, () => new MessageChannel());
    for (let index = 0; index < 8; index += 1) {
      expect(broker.handleWindowMessage(requestEvent(channels[index], "diagnostics", `request-${index}`))).toBe(true);
      await expect(nextMessage(channels[index].port1)).resolves.toMatchObject({
        type: PWA_CACHE_OPERATIONS_ACCEPTED,
      });
    }

    broker.handleWindowMessage(requestEvent(channels[8], "diagnostics", "request-over-limit"));
    await nextMessage(channels[8].port1);
    await expect(nextMessage(channels[8].port1)).resolves.toMatchObject({
      status: "unavailable",
      type: PWA_CACHE_OPERATIONS_RESULT,
    });
    expect(lifecycle.diagnostics).toHaveBeenCalledTimes(8);
    broker.dispose();
  });
});

function diagnostics(overrides: Record<string, unknown> = {}) {
  return {
    backend: "indexeddb" as const,
    cacheBytes: 12,
    entryCount: 1,
    fileCacheAvailable: true,
    fileCacheBytes: 0,
    fileCacheEntryCount: 0,
    originQuotaBytes: 1_000,
    originUsageBytes: 12,
    pendingCleanupCount: 0,
    structuredCacheBytes: 12,
    structuredEntryCount: 1,
    ...overrides,
  };
}
