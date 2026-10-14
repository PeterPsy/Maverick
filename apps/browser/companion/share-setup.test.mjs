import test from "node:test";
import assert from "node:assert/strict";
import {createShareSetup} from "./share-setup.mjs";

test("the worker owns consent and continues once after the popup disappears", async t => {
  const previous = globalThis.chrome, calls = [];
  t.after(() => {globalThis.chrome = previous;});
  let grant;
  globalThis.chrome = {permissions:{request(options) {
    calls.push(options); return new Promise(resolve => {grant = resolve;});
  }}};
  const start = createShareSetup(async message => {calls.push(message); return {status:"shared"};});
  const message = {url:"https://loopino.test/app/browser?connector=1",tabId:12,agentTab:true};
  const first = start(message), second = start(message);
  assert.equal(first, second);
  assert.equal(calls.length, 1, "Permission request must run synchronously within the message's user gesture");
  assert(calls[0].origins.includes("https://loopino.test/*"));
  assert(calls[0].origins.includes("https://*/*"));
  assert(!calls[0].origins.includes("http://*/*"));
  grant(true);
  assert.deepEqual(await first, {status:"shared"});
  assert.equal(calls.length, 2, "No popup callback or second click is needed to share");
});

test("denial and invalid setup never start sharing and permit a later explicit retry", async t => {
  const previous = globalThis.chrome;
  t.after(() => {globalThis.chrome = previous;});
  let permitted = false, started = 0;
  globalThis.chrome = {permissions:{async request() {return permitted;}}};
  const start = createShareSetup(async () => {started++; return {status:"shared"};});
  const message = {url:"https://loopino.test/app/browser",tabId:12,agentTab:true};
  await assert.rejects(start({...message, agentTab:false, platform:"instagram"}), /agent_tab_required/u);
  await assert.rejects(start({...message, agentTab:"true"}), /agent_tab_required/u);
  await assert.rejects(start(message), /permission_denied/u);
  assert.equal(started, 0);
  permitted = true;
  assert.equal((await start(message)).status, "shared");
  assert.equal(started, 1);
});
