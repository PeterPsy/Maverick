import test from "node:test";
import assert from "node:assert/strict";
import {attachConnectorFrame} from "./connector-frame.mjs";

test("fresh connector waits for login, selects one Browser document and fences sharing replacement",async t=>{
  const origin="https://maverick.test",url="https://af-0123456789abcdef01234567.sidecars.maverick.test/apps/browser/";
  const b={sharingId:"selected",connectorTabId:10,origin,path:"/app/browser"};
  let current=b,frames=[],writes=0;const injections=[];
  const originalChrome=globalThis.chrome;
  t.after(()=>{if(originalChrome === undefined)delete globalThis.chrome;else globalThis.chrome=originalChrome;});
  globalThis.chrome={tabs:{async get(){return {id:10,url:`${origin}/app/browser?connector=1`};}},
    storage:{session:{async set({binding}){current=binding;writes++;}}},
    scripting:{async executeScript(options){injections.push(options);return options.func ? frames : [];}}};
  assert.equal((await attachConnectorFrame(b,async()=>current)).status,"waiting_for_browser");
  assert.equal(writes,0);
  frames=[{frameId:3,documentId:"fresh",result:{url,platformOrigin:origin}},{frameId:4,documentId:"chat",result:null}];
  const attached=await attachConnectorFrame(b,async()=>current);
  assert.equal(attached.binding.connectorDocumentId,"fresh");assert.equal(attached.binding.connectorFrameId,3);
  assert.deepEqual(injections.at(-1).target,{tabId:10,documentIds:["fresh"]});
  assert.deepEqual(injections.at(-1).files,["content.js"]);
  frames.push({...frames[0],documentId:"another-browser"});
  assert.equal((await attachConnectorFrame(b,async()=>current)).status,"waiting_for_browser");assert.equal(writes,1);
  frames.pop();current={...current,sharingId:"replacement"};
  await assert.rejects(attachConnectorFrame(b,async()=>current),/sharing_revoked/u);assert.equal(writes,1);
});
