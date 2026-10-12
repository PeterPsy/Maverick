import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { callBackend } from "../src/api";

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function stalledFetch() {
  return vi.fn((_url: string, options: RequestInit) => new Promise<Response>((_resolve, reject) => {
    options.signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
}
it("bounds stalled requests and preserves send uncertainty on a timeout", async () => {
  vi.stubGlobal("fetch", stalledFetch());
  const result = callBackend({ action: "messages.send" });
  const check = expect(result).rejects.toMatchObject({ status: 504, code: "request_timeout",
    message: expect.stringContaining("may already have been sent") });
  await vi.advanceTimersByTimeAsync(28000);
  await check;
  expect(vi.getTimerCount()).toBe(0);
});
it("propagates read cancellation without classifying it as a timeout", async () => {
  const fetch = stalledFetch();
  vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  const result = callBackend({ action: "chats.list" }, controller.signal);
  const check = expect(result).rejects.toMatchObject({ name: "AbortError" });
  controller.abort();
  await check;
  expect(fetch.mock.calls[0][1].signal!.aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});
it("reports malformed successful responses and non-JSON HTTP errors clearly", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response("broken", { status: 200 }))
    .mockResolvedValueOnce(new Response("<h1>Unauthorized</h1>", { status: 401 })));
  await expect(callBackend({ action: "status" })).rejects.toMatchObject({ status: 502, code: "invalid_response" });
  await expect(callBackend({ action: "status" })).rejects.toMatchObject({ status: 401, message: "Request failed (401)." });
});
