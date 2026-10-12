import test from "node:test";
import assert from "node:assert/strict";
import {createAgentTabRegistry} from "./agent-tab.mjs";
import {selectedAgentTab} from "./setup.mjs";

test("disconnect preserves the navigated agent identity and opening reuses that tab", async () => {
  const state = {}, tabs = new Map(), created = [], focused = [];
  const startUrl = "chrome-extension://fixture/agent-tab.html";
  const chrome = {
    storage: {session: {
      async get(key) {return {[key]:state[key]};},
      async set(value) {Object.assign(state,value);},
      async remove(key) {delete state[key];},
    }},
    tabs: {
      async get(id) {if(!tabs.has(id))throw new Error("tab_closed");return tabs.get(id);},
      async query({url}) {return [...tabs.values()].filter(tab=>tab.url === url);},
      async update(id, value) {const tab={...tabs.get(id),...value};tabs.set(id,tab);return tab;},
      async create({url}) {const tab={id:tabs.size+10,url,windowId:1};tabs.set(tab.id,tab);created.push(tab);return tab;},
    },
    windows: {async update(id) {focused.push(id);}},
  };
  const registry=createAgentTabRegistry(chrome,startUrl,()=>"identity-one");
  const opened=await registry.open();
  const identity=await registry.get();
  assert.equal(identity.tabId,opened.id);
  assert.equal(identity.id,"identity-one");
  assert.equal(identity.allowedPlatforms.length,6);
  tabs.get(opened.id).url="https://www.instagram.com/";
  state.binding={tabId:opened.id};
  await chrome.storage.session.remove("binding");
  const reused=await registry.open();
  assert.equal(reused.id,opened.id);
  assert.equal(reused.url,"https://www.instagram.com/");
  assert.equal(created.length,1);
  assert.equal(selectedAgentTab(reused,startUrl,await registry.get()).reconnect,true);
  assert.throws(()=>selectedAgentTab({...reused,id:99},startUrl,identity),/agent_tab_required/u);
  assert.equal((await registry.remember(reused)).id,identity.id);
  // A login navigation can stop sharing; identity still lets the user return.
  tabs.get(opened.id).url="https://www.instagram.com/accounts/login/";
  assert.equal((await registry.open()).id,opened.id);
  assert.equal(selectedAgentTab(tabs.get(opened.id),startUrl,identity).reconnect,true);
  await registry.forget(99);
  assert.equal((await registry.get()).id,identity.id);
  tabs.delete(opened.id);
  await registry.forget(opened.id);
  assert.equal(await registry.get(),undefined);
  const replacement=await registry.open();
  assert.equal(replacement.url,startUrl);
  assert.equal(created.length,2);
  assert(focused.length>=3);
});

test("an existing empty start page is reused before creating another tab", async () => {
  let identity;
  const tab={id:7,url:"chrome-extension://fixture/agent-tab.html",windowId:1};
  const chrome={
    storage:{session:{async get(){return {agentTab:identity};},async set(value){identity=value.agentTab;},async remove(){identity=undefined;}}},
    tabs:{async query(){return [tab];},async update(){return tab;},async create(){assert.fail("Duplicate tab created");}},
    windows:{async update(){}},
  };
  assert.equal((await createAgentTabRegistry(chrome,tab.url,()=>"identity").open()).id,7);
  assert.equal(identity.tabId,7);
});
