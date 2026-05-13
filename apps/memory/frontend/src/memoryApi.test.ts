import { describe, expect, it, vi } from "vitest";
import { callMemory, currentMemoryAppId, memoryBackendEndpoint } from "./memoryApi";

describe("memory api client", () => {
  it("derives the mounted app backend from the current app route", () => {
    expect(currentMemoryAppId("/apps/memory-fork/widgets/memory-sidebar/")).toBe("memory-fork");
    expect(currentMemoryAppId("/api/apps/widgets/memory-fork/memory-sidebar-footer/frontend/")).toBe("memory-fork");
    expect(memoryBackendEndpoint("memory-fork")).toBe("/api/apps/memory-fork/backend");
    expect(currentMemoryAppId("/app/memory/nodes/node-1")).toBe("memory");
  });

  it("unwraps successful app payloads", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ json: { nodes: [{ id: "node-1" }] } }), { status: 200 }));

    await expect(callMemory<{ nodes: Array<{ id: string }> }>({ action: "graph" }, { fetchImpl })).resolves.toEqual({
      nodes: [{ id: "node-1" }],
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/apps/memory/backend",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "graph" }) }),
    );
  });

  it("throws normalized errors for HTTP and app status failures", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ error: "validation_error", detail: "title is required." }), { status: 400 }));

    await expect(callMemory({ action: "remember" }, { fetchImpl })).rejects.toMatchObject({
      code: "validation_error",
      detail: "title is required.",
      status: 400,
    });
  });

  it("prefers app status codes over successful HTTP status", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            status_code: 422,
            json: { error: "validation_error", detail: "limit must be an integer." },
          }),
          { status: 200 },
        ),
    );

    await expect(callMemory({ action: "graph", limit: "many" }, { fetchImpl })).rejects.toMatchObject({
      code: "validation_error",
      detail: "limit must be an integer.",
      status: 422,
    });
  });

  it("supports caller cancellation", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn(
      () =>
        new Promise<Response>((_resolve, reject) => {
          controller.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );

    const request = callMemory({ action: "graph" }, { fetchImpl, signal: controller.signal });
    const assertion = expect(request).rejects.toMatchObject({ code: "request_cancelled" });
    controller.abort();

    await assertion;
  });

  it("times out stalled requests", async () => {
    vi.useFakeTimers();
    try {
      const fetchImpl = vi.fn(
        (_url: string | URL | Request, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
      );

      const request = callMemory({ action: "graph" }, { fetchImpl, timeoutMs: 5 });
      const assertion = expect(request).rejects.toMatchObject({ code: "request_timeout", status: 408 });
      await vi.advanceTimersByTimeAsync(5);

      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });
});
