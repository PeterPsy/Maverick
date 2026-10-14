import test from "node:test";
import assert from "node:assert/strict";
import {openConnectorWindow} from "./connector-window.mjs";

test("reuse selects the existing Loopino shell at the exact origin, excluding private routes and the source", async t => {
  const previous = globalThis.chrome, calls = [];
  t.after(() => { if (previous === undefined) delete globalThis.chrome; else globalThis.chrome = previous; });
  const url = new URL("https://loopino.test/app/browser?connector=1");
  let tabs = [
    {id: 1, url: "https://other.test/app/browser", lastAccessed: 100},
    {id: 2, url: "https://loopino.test/api/private", lastAccessed: 100},
    {id: 3, url: url.href, lastAccessed: 90},
    {id: 4, url: "https://loopino.test/app/browser", lastAccessed: 80},
    {id: 5, url: "https://loopino.test/app/chat", lastAccessed: 70},
  ];
  globalThis.chrome = {
    tabs: {
      async query(query) { assert.deepEqual(query, {}); return tabs; },
      async get(id) { if (id === 4) throw new Error("Tab closed"); return tabs.find(tab => tab.id === id); },
      async update(id, options) { calls.push({id, options}); return {id, windowId: 20}; },
    },
    windows: {
      async getAll(){return [];},
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

test("a tab that leaves the Loopino shell during selection is not redirected", async t => {
  const previous = globalThis.chrome;
  t.after(() => { if (previous === undefined) delete globalThis.chrome; else globalThis.chrome = previous; });
  globalThis.chrome = {
    tabs: {async query() {return [{id: 1, url: "https://loopino.test/app/browser"}];},
      async get() {return {id: 1, url: "https://loopino.test/login"};},
      async update() {assert.fail("Another app must not be redirected");}},
    windows: {async getAll(){return [];},async create() {return {tabs: [{id: 2}]};}},
  };
  assert.equal((await openConnectorWindow(new URL("https://loopino.test/app/browser?connector=1"))).id, 2);
});

test("a loading shell in another window is reused and a fresh setup adds a tab without a popup",async t=>{
  const original=globalThis.chrome,calls=[];
  t.after(()=>{if(original === undefined)delete globalThis.chrome;else globalThis.chrome=original;});
  let tabs=[{id:5,windowId:2,url:"about:blank",pendingUrl:"https://loopino.test/app/chat"}];
  globalThis.chrome={tabs:{async query(){return tabs;},async get(){return tabs[0];},async update(id,p){calls.push({id,p});return {id,windowId:2};},async create(p){calls.push({create:p});return {id:6,windowId:p.windowId};}},
    windows:{async getAll(){return [{id:2,type:"normal",focused:true}];},async update(){},async create(){assert.fail("No duplicate window");}}};
  const url=new URL("https://loopino.test/app/browser?connector=1");
  assert.equal((await openConnectorWindow(url,{sourceTabId:1})).id,5);
  tabs=[];
  assert.equal((await openConnectorWindow(url,{sourceTabId:1})).id,6);
  assert.equal(calls.at(-1).create.windowId,2);
});
