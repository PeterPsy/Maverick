import test from "node:test";
import assert from "node:assert/strict";
import {setImmediate as turn} from "node:timers/promises";
import {createBackgroundConnector} from "./background-connector.mjs";

function fixture() {
  let b={sharingId:"share",connectorFrameOrigin:"https://af-selected.sidecars.loopino.test",agentTabId:"agent",allowedPlatforms:[],accessMode:"interactive",websiteScope:"https"};
  const state={backgroundToken:"bounded-grant",lease:{connection:{session_id:"chrome-selected"},connector_secret:"only-extension-knows"},completion:null};
  const requests=[],executed=[],stopped=[];let command=null,failCompletion=false,failPoll=false,release=null,delayExecution=false;
  const session={async background(){return structuredClone(state);},async ack(_b,id){if(state.completion?.operation_id===id)state.completion=null;},async save(_b,lease){state.lease=lease;state.completion=null;}};
  const connector=createBackgroundConnector({binding:async()=>b,session,status:async()=>({url:"https://public.test/",title:"Fixture",active_operation:release ? "action" : null}),
    execute:async(_b,next)=>{executed.push(next.operation_id);if(delayExecution)await new Promise(resolve=>{release=resolve;});state.completion={operation_id:next.operation_id,lease_id:next.lease_id,result:{changed:true}};release=null;},
    cancel:id=>requests.push({cancel:id}),stop:async(reason)=>{stopped.push(reason);b=null;},fetch:async(url,options)=>{
      const body=options.body ? JSON.parse(options.body) : {};
      assert.equal(new URL(url).origin,"https://af-selected.sidecars.loopino.test");assert.equal(options.credentials,"omit");assert.equal(options.redirect,"error");
      requests.push(body);
      if(body.action === "companion.complete" && failCompletion){failCompletion=false;throw new Error("network lost");}
      const data=body.action === "companion.poll" ? (failPoll ? {error:"background_authorization_expired"} : {command}) : {status:"cancelled"};
      if(body.action === "companion.poll")command=null;
      return {ok:!data.error,status:data.error ? 403 : 200,json:async()=>data};
    }});
  return {connector,requests,executed,stopped,state,command:value=>{command=value;},failCompletion:()=>{failCompletion=true;},failPoll:()=>{failPoll=true;},delay:()=>{delayExecution=true;},release:()=>release?.()};
}
const command={operation_id:"action",lease_id:"claim",action:"click",expires_at:Date.now()/1000+60};

test("background loop runs without a Loopino document and delivers lost results without replay",async()=>{
  const f=fixture();f.command(command);await f.connector.tick();await turn();
  assert.deepEqual(f.executed,["action"]);
  f.failCompletion();await f.connector.tick();assert(f.state.completion);
  await f.connector.tick();assert.equal(f.state.completion,null);
  assert.deepEqual(f.executed,["action"]);
  assert.equal(f.requests.filter(r=>r.action === "companion.complete").length,2);
});

test("cancelled work drains before the next background command can be claimed",async()=>{
  const f=fixture();f.delay();f.command(command);await f.connector.tick();
  f.command({...command,operation_id:"next"});await f.connector.tick();
  assert(f.requests.some(r=>r.cancel === "action"));
  assert.deepEqual(f.executed,["action"]);
  assert.equal(f.requests.filter(r=>r.action === "companion.poll").at(-1).active_operation_id,"action");
  f.release();await turn();
});

test("loss of the issuing login stops sharing and Disconnect revokes both leases",async()=>{
  const f=fixture();f.failPoll();await f.connector.tick();
  assert.deepEqual(f.stopped,["background_authorization_expired"]);
  const other=fixture();await other.connector.disconnect({connectorFrameOrigin:"https://af-selected.sidecars.loopino.test"});
  assert(other.requests.some(r=>r.action === "companion.disconnect" && r.reason === "user_stopped"));
});
