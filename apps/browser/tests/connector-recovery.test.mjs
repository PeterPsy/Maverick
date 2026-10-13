import test from "node:test";
import assert from "node:assert/strict";

test("reload resumes the live lease, expiry replaces it, and completion delivery is never an action replay",async t=>{
  const origin="https://af-browser.sidecars.maverick.test",listeners=[],calls=[],sent=[];
  const lease={connection:{session_id:"old"},connector_secret:"private"};
  let owned={session_id:"old",status:"connected",expires_at:Date.now()/1000+100};
  const previous={window:globalThis.window,location:globalThis.location};
  globalThis.location={origin};
  globalThis.window={addEventListener(_event,listener){listeners.push(listener);},postMessage(message){sent.push(message.action);queueMicrotask(()=>{
    for(const listener of listeners)listener({source:window,origin,data:{type:"maverick.browser.response",id:message.id,result:message.action === "lease.restore" ? {lease} : {saved:true}}});
  });}};
  t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value === undefined)delete globalThis[key];else globalThis[key]=value;}});
  t.mock.method(globalThis,"fetch",async(_url,options)=>{
    const body=JSON.parse(options.body);calls.push(body);
    const value=body.action === "companion.overview" ? {connections:owned ? [owned] : []} : body.action === "companion.connect" ? {...lease,connection:{session_id:"new"}} : {status:"completed"};
    if(body.action === "companion.complete")return {ok:false,status:409,async json(){return {error:"operation_not_running"};}};
    return {ok:true,status:200,async json(){return value;}};
  });
  const {acquireConnectorLease,deliverConnectorCompletion}=await import("../frontend/src/connector-recovery.js");
  const shared={lease_recovery:true,agent_tab_id:"approved"};
  assert.equal((await acquireConnectorLease(shared)).connection.session_id,"old");
  assert.equal(calls.filter(c=>c.action === "companion.connect").length,0);
  owned.expires_at=Date.now()/1000-1;
  assert.equal((await acquireConnectorLease(shared)).connection.session_id,"new");
  assert(sent.includes("lease.store"));
  owned=null;
  await assert.rejects(acquireConnectorLease(shared),/account changed/u);
  assert.equal(calls.filter(c=>c.action === "companion.connect").length,1);
  await deliverConnectorCompletion({session_id:"old",connector_secret:"private"},{operation_id:"performed",lease_id:"claim",result:{performed:true}});
  assert.equal(sent.at(-1),"completion.ack");
  assert(!sent.includes("execute"));
});
