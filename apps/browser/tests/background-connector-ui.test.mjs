import test from "node:test";
import assert from "node:assert/strict";
import {setImmediate as turn} from "node:timers/promises";

test("a reloaded background UI leaves lease renewal and polling to the extension",async t=>{
  const prior={window:globalThis.window,location:globalThis.location};
  const listeners=[],actions=[];
  const origin="https://af-fixture.sidecars.maverick.test";
  const lease={connection:{session_id:"chrome-background"},connector_secret:"only-bound-ui"};
  globalThis.location={origin};
  globalThis.window={addEventListener(_event,listener){listeners.push(listener);},postMessage(message){
    actions.push(message.action);
    const result=message.action === "status" ? {background_connector:true,background_active:true,title:"Agent tab"} : message.action === "lease.restore" ? {lease} : {};
    queueMicrotask(()=>listeners.forEach(listener=>listener({source:window,origin,data:{type:"maverick.browser.response",id:message.id,result}})));
  }};
  t.mock.method(globalThis,"fetch",async(_url,options)=>{
    assert.equal(JSON.parse(options.body).action,"companion.disconnect","The UI must never connect, claim or complete a background operation");
    return {ok:true,status:200,json:async()=>({})};
  });
  const {createConnector}=await import("../frontend/src/connector.js");
  const connector=createConnector(()=>{});
  t.after(async()=>{await connector.stop();for(const [key,value] of Object.entries(prior)){if(value === undefined)delete globalThis[key];else globalThis[key]=value;}});
  assert.deepEqual(await connector.start(),lease.connection);
  await turn();
  assert(actions.includes("lease.restore"));assert(actions.includes("background.start"));
  assert(!actions.includes("execute"));
});
