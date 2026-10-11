import test from "node:test";
import assert from "node:assert/strict";
import {openConnectorWindow} from "./connector-window.mjs";

test("reuse selects the existing Maverick shell at the exact origin, excluding private routes and the source", async t => {
  const previous = globalThis.chrome, calls = [];
  t.after(() => { if (previous === undefined) delete globalThis.chrome; else globalThis.chrome = previous; });
  const url = new URL("https://maverick.test/app/browser?connector=1");
  let tabs = [
    {id: 1, url: "https://other.test/app/browser", lastAccessed: 100},
    {id: 2, url: "https://maverick.test/api/private", lastAccessed: 100},
    {id: 3, url: url.href, lastAccessed: 90},
    {id: 4, url: "https://maverick.test/app/browser", lastAccessed: 80},
    {id: 5, url: "https://maverick.test/app/chat", lastAccessed: 70},
  ];
  globalThis.chrome = {
    tabs: {
      async query(query) { assert.equal(query.url, "https://maverick.test/*"); return tabs; },
      async get(id) { if (id === 4) throw new Error("Tab closed"); return tabs.find(tab => tab.id === id); },
      async update(id, options) { calls.push({id, options}); return {id, windowId: 20}; },
    },
    windows: {
      async update(id, options) { calls.push({windowId: id, options}); },
      async create(options) { calls.push({create: options}); return {tabs: [{id: 30}]}; },
    },
  };
  assert.equal((await openConnectorWindow(url, {sourceTabId: 3})).id, 5);
  assert.deepEqual(calls, [{id: 5, options: {url: url.href, active: true}}, {windowId: 20, options: {focused: true}}]);
  calls.length = 0;
  assert.equal((await openConnectorWindow(url, {reuse: false})).id, 30);
  assert.equal(calls[0].create.url, url.href);
  calls.length = 0; tabs = [];
  assert.equal((await openConnectorWindow(url)).id, 30);
  assert.equal(calls[0].create.type, "popup");
});

test("a tab that leaves the Maverick shell during selection is not redirected", async t => {
  const previous = globalThis.chrome;
  t.after(() => { if (previous === undefined) delete globalThis.chrome; else globalThis.chrome = previous; });
  globalThis.chrome = {
    tabs: {async query() {return [{id: 1, url: "https://maverick.test/app/browser"}];},
      async get() {return {id: 1, url: "https://maverick.test/login"};},
      async update() {assert.fail("Another app must not be redirected");}},
    windows: {async create() {return {tabs: [{id: 2}]};}},
  };
  assert.equal((await openConnectorWindow(new URL("https://maverick.test/app/browser?connector=1"))).id, 2);
});
