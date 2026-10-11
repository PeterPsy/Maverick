import test from "node:test";
import assert from "node:assert/strict";

test("backend requests preserve authorization errors and abort hung or obsolete reads", async t => {
  const previous = globalThis.window;
  globalThis.window = {addEventListener() {}};
  t.after(() => { if (previous === undefined) delete globalThis.window; else globalThis.window = previous; });
  const {request} = await import("../frontend/src/api.js");
  t.mock.method(globalThis, "fetch", async () => ({ok: false, status: 401, json: async () => { throw new Error("HTML"); }}));
  await assert.rejects(request({action: "companion.overview"}), error => error.status === 401);
  t.mock.method(globalThis, "fetch", (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), {once: true});
  }));
  t.mock.timers.enable({apis: ["setTimeout"]});
  const timed = assert.rejects(request({action: "companion.overview"}, {timeoutMs: 100}), /did not respond in time/);
  t.mock.timers.tick(100); await timed;
  const controller = new AbortController();
  const cancelled = assert.rejects(request({action: "companion.overview"}, {signal: controller.signal}), {name: "AbortError"});
  controller.abort(); await cancelled;
});
