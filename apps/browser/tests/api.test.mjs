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

test("Companion status and operation timeouts preserve distinct actionable failures", async t => {
  const previous={window:globalThis.window,location:globalThis.location};
  globalThis.window={addEventListener(){},postMessage(){}};
  globalThis.location={origin:"https://browser-fixture.test"};
  t.after(()=>{for(const [key,value] of Object.entries(previous)) {if(value===undefined)delete globalThis[key];else globalThis[key]=value;}});
  const {bridge}=await import("../frontend/src/api.js");
  t.mock.timers.enable({apis:["setTimeout"]});
  const status=assert.rejects(bridge("status",undefined,100),error=>error.code === "companion_unavailable" && /Open agent tab/u.test(error.message));
  t.mock.timers.tick(100);await status;
  const operation=assert.rejects(bridge("execute",{},100),error=>error.code === "companion_command_timeout" && /Keep the shared tab/u.test(error.message));
  t.mock.timers.tick(100);await operation;
});
