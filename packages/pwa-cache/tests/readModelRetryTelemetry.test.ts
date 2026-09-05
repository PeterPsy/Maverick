import { afterEach, expect, it, vi } from "vitest";
import { readCacheModelJson } from "../src/readModelRetry";
import { bindReadModelRetryTelemetry, readModelRetryTelemetry } from "../src/readModelRetryTelemetry";

const scope = { appId: "app-store", resource: "catalog" };
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("binds only the matching read scope and signal, not arbitrary loader callbacks", () => {
  const signal = new AbortController().signal;
  const record = vi.fn();
  const unbind = bindReadModelRetryTelemetry(signal, scope, record);
  expect(readModelRetryTelemetry(scope)).toBeUndefined();
  expect(readModelRetryTelemetry(scope, new AbortController().signal)).toBeUndefined();
  expect(readModelRetryTelemetry({ ...scope, appId: "storage" }, signal)).toBeUndefined();
  expect(readModelRetryTelemetry({ ...scope, resource: "other" }, signal)).toBeUndefined();
  const observer = readModelRetryTelemetry(scope, signal)!;
  unbind();
  observer({ attempt: 0, keyHash: "deadbeef", kind: "wait_started" });
  expect(record).not.toHaveBeenCalled();
});

it("does not let late cleanup or events from an old binding affect a replacement", () => {
  const signal = new AbortController().signal;
  const old = vi.fn();
  const current = vi.fn();
  const releaseOld = bindReadModelRetryTelemetry(signal, scope, old);
  const oldObserver = readModelRetryTelemetry(scope, signal)!;
  const releaseCurrent = bindReadModelRetryTelemetry(signal, scope, current);
  releaseOld();
  const event = { attempt: 0, keyHash: "deadbeef", kind: "wait_started" as const };
  oldObserver(event);
  readModelRetryTelemetry(scope, signal)!(event);
  expect(old).not.toHaveBeenCalled();
  expect(current).toHaveBeenCalledExactlyOnceWith(event);
  releaseCurrent();
});

it("observes the SDK-owned transport wait, actual retry and resolution", async () => {
  vi.useFakeTimers();
  const signal = new AbortController().signal;
  const record = vi.fn();
  const release = bindReadModelRetryTelemetry(signal, scope, record);
  vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("down")).mockResolvedValueOnce(Response.json({ ok: true }));
  const result = readCacheModelJson(scope, signal);
  await vi.advanceTimersByTimeAsync(1_250);
  await expect(result).resolves.toEqual({ ok: true });
  expect(record.mock.calls.map(([event]) => event.kind)).toEqual(["wait_started", "retry_attempt", "resolved"]);
  release();
});
