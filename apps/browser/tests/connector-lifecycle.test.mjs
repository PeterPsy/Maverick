import test from "node:test";
import assert from "node:assert/strict";
import {setImmediate as nextTurn} from "node:timers/promises";

test("connector starts once, throttles auth renewal and revokes a late connection after stop", async t => {
  const origin = "https://browser-fixture.test", listeners = [], calls = [], states = [];
  let delayed = false, release, serial = 0, connector;
  const previous = {window: globalThis.window, location: globalThis.location};
  globalThis.location = {origin};
  const dispatch = data => listeners.forEach(listener => listener({source: window, origin, data}));
  globalThis.window = {
    addEventListener(_type, listener) { listeners.push(listener); },
    postMessage(message) { queueMicrotask(() => dispatch({type: "maverick.browser.response", id: message.id,
      result: message.action === "status" ? {url: "https://www.instagram.com/fixture/"} : {}})); },
  };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : {};
    calls.push({url, ...body});
    let result = {};
    if (body.action === "companion.connect") {
      result = {connection: {session_id: `session-${++serial}`}, connector_secret: "fixture"};
      if (delayed) await new Promise(resolve => { release = resolve; });
    }
    return {ok: true, status: 200, async json() { return result; }};
  });
  t.after(async () => {
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
  connector = createConnector((_text, state) => states.push(state));
  const first = connector.start(); assert.equal(connector.start(), first); await first;
  await until(() => calls.filter(call => call.url.startsWith("/.well-known")).length === 1);
  await nextTurn(); dispatch({type: "maverick.browser.wake"});
  await until(() => calls.filter(call => call.action === "companion.poll").length === 2);
  assert.equal(calls.filter(call => call.url.startsWith("/.well-known")).length, 1);
  assert.equal(calls.filter(call => call.action === "companion.connect").length, 1);
  await connector.stop(); assert.equal(states.at(-1), "stopped");
  delayed = true; const pending = connector.start();
  const rejection = assert.rejects(pending, /Sharing was stopped/);
  await until(() => Boolean(release)); await connector.stop(); release(); await rejection;
  assert.ok(calls.some(call => call.action === "companion.disconnect" && call.session_id === "session-2"));
  assert.equal(calls.filter(call => call.action === "companion.poll").length, 2);
});
