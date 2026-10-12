import test from "node:test";
import assert from "node:assert/strict";
import {setImmediate as nextTurn} from "node:timers/promises";

test("connector starts once, throttles renewal, fences stop and preserves sharing across cancellation races", async t => {
  const origin = "https://browser-fixture.test", listeners = [], calls = [], states = [], reports = [], renewals = [];
  let delayed = false, release, serial = 0, connector, nextCommand, executing, cancelled = false, statusFailure = true;
  const previous = {window: globalThis.window, location: globalThis.location};
  globalThis.location = {origin};
  const dispatch = data => listeners.forEach(listener => listener({source: window, origin, data}));
  globalThis.window = {
    addEventListener(_type, listener) { listeners.push(listener); },
    postMessage(message) {
      if (message.action === "execute") {executing = message; return;}
      if (message.action === "cancel") cancelled = true;
      queueMicrotask(() => dispatch({type: "maverick.browser.response", id: message.id,
        result: message.action === "status" ? (statusFailure ? {error:"connector_scope_required"} : {url: "https://www.instagram.com/fixture/", agent_tab_id:"5394d8de-023e-4e63-acf3-cdc9d56e2aee", active_operation: executing?.command.operation_id}) : {}}));
    },
  };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : {};
    calls.push({url, ...body});
    if (url.startsWith("/.well-known")) return new Promise(resolve => renewals.push(() => resolve({ok:true,status:204})));
    let result = {};
    if (body.action === "companion.connect") {
      result = {connection: {session_id: `session-${++serial}`}, connector_secret: "fixture"};
      if (delayed) await new Promise(resolve => { release = resolve; });
    }
    if (body.action === "companion.poll" && nextCommand) { result = {command: nextCommand}; nextCommand = null; }
    if (body.action === "operation.get") result = {status: "running"};
    if (body.action === "companion.progress" || body.action === "companion.complete") return {
      ok: false, status: 409, async json() {return {error: "operation_not_running", detail: "The operation was cancelled."};},
    };
    return {ok: true, status: 200, async json() { return result; }};
  });
  t.after(async () => {
    renewals.forEach(resolve => resolve());
    release?.(); await connector?.stop();
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[key]; else globalThis[key] = value;
    }
  });
  const until = async predicate => {
    for (let i = 0; i < 100; i++) { if (predicate()) return; await nextTurn(); }
    assert.fail("Connector did not settle.");
  };
  const {createConnector} = await import("../frontend/src/connector.js");
  connector = createConnector((text, state) => {states.push(state); reports.push(text);});
  await assert.rejects(connector.start(), /Open agent tab/u);
  assert.equal(states.at(-1), "stopped", "A failed start must leave Connecting and permit retry");
  assert.equal(calls.filter(call => call.action === "companion.connect").length, 0);
  statusFailure = false;
  const first = connector.start(); assert.equal(connector.start(), first); await first;
  await until(() => calls.filter(call => call.url.startsWith("/.well-known")).length === 1);
  await nextTurn(); dispatch({type: "maverick.browser.wake"});
  await until(() => calls.filter(call => call.action === "companion.poll").length === 2);
  renewals.shift()();
  assert.equal(calls.filter(call => call.url.startsWith("/.well-known")).length, 1);
  assert.equal(calls.filter(call => call.action === "companion.connect").length, 1);
  assert.equal(calls.find(call => call.action === "companion.connect").agent_tab_id,"5394d8de-023e-4e63-acf3-cdc9d56e2aee");
  await connector.stop(); assert.equal(states.at(-1), "stopped");
  delayed = true; const pending = connector.start();
  const rejection = assert.rejects(pending, /Sharing was stopped/);
  await until(() => Boolean(release)); await connector.stop(); release(); await rejection;
  assert.ok(calls.some(call => call.action === "companion.disconnect" && call.session_id === "session-2"));
  assert.equal(calls.filter(call => call.action === "companion.poll").length, 2);
  delayed = false;
  nextCommand = {operation_id: "cancel-race", lease_id: "fixture-lease", action: "video.analyze", expires_at: Date.now() / 1000 + 60};
  await connector.start(); await until(() => Boolean(executing)); await nextTurn();
  const disconnects = calls.filter(call => call.action === "companion.disconnect").length;
  dispatch({type: "maverick.browser.wake"}); await until(() => cancelled);
  await until(() => calls.some(call => call.action === "companion.poll" && call.active_operation_id === "cancel-race"));
  assert.equal(calls.filter(call => call.action === "companion.disconnect").length, disconnects, "An operation cancellation race must not revoke sharing");
  const pendingExecution = executing; executing = null;
  dispatch({type: "maverick.browser.response", id: pendingExecution.id, result: {error: "operation_cancelled"}});
  await nextTurn(); await nextTurn();
  dispatch({type: "maverick.browser.wake"});
  await until(() => calls.filter(call => call.action === "companion.poll").length >= 5);
  assert.equal(calls.filter(call => call.action === "companion.disconnect").length, disconnects);
  await nextTurn(); statusFailure = true;
  dispatch({type: "maverick.browser.wake"});
  await until(() => calls.filter(call => call.action === "companion.disconnect").length === disconnects + 1);
  assert.equal(states.at(-1), "stopped", "A scoped bridge failure must revoke on the first response even when its message contains friendly guidance");
  assert.match(reports.at(-1), /Sharing stopped:.*Open agent tab/u);
  assert.equal(calls.filter(call => call.action === "companion.disconnect").at(-1).reason, "connector_scope_required");
});
