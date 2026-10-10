import test from "node:test";
import assert from "node:assert/strict";
import {setImmediate as nextTurn} from "node:timers/promises";

test("Cancellation waits for the Chrome worker cleanup before claiming the next command",async t=>{
  const listeners=[],polls=[],executed=[],completed=[];
  let active=null,releaseFirst,connector;
  const origin="https://browser-fixture.test";
  const dispatch=data=>{for(const listener of listeners)listener({source:window,origin,data});};
  const command=id=>({operation_id:id,action:"video.analyze",lease_id:id,expires_at:Date.now()/1000+60});
  const commands=[command("first"),command("second")];
  const previous={window:globalThis.window,location:globalThis.location};
  globalThis.location={origin};
  globalThis.window={
    addEventListener(_type,listener){listeners.push(listener);},
    postMessage(message){
      queueMicrotask(async()=>{
        let result={};
        if(message.action === "status")result={url:"https://www.instagram.com/fixture/",active_operation:active};
        if(message.action === "execute") {
          const id=message.command.operation_id;executed.push(id);
          if(active)result={error:"operation_already_running"};
          else if(id === "first") {
            active=id;
            result=await new Promise(resolve=>{releaseFirst=()=>{active=null;resolve({error:"operation_cancelled"});};});
          } else result={text:"next observation"};
        }
        // A cancellation acknowledgement does not mean video restoration has finished.
        if(message.action === "cancel")result={cancelled:true};
        dispatch({type:"maverick.browser.response",id:message.id,result});
      });
    },
  };
  t.mock.method(globalThis,"fetch",async(_url,options)=>{
    const body=options.body ? JSON.parse(options.body) : {};
    let json={},status=200;
    if(body.action === "companion.connect")json={connection:{session_id:"fixture"},connector_secret:"fixture"};
    if(body.action === "companion.poll") {
      polls.push(body);
      json={command:body.active_operation_id ? null : commands.shift() || null};
    }
    if(body.action === "operation.get")json={status:"cancelled"};
    if(body.action === "companion.complete") {
      if(body.operation_id === "first"){status=409;json={error:"operation_not_running"};}
      else completed.push(body);
    }
    return {ok:status<400,status,async json(){return json;}};
  });
  t.after(async()=>{
    releaseFirst?.();await connector?.stop();
    for(const [key,value] of Object.entries(previous)) {
      if(value === undefined)delete globalThis[key];else globalThis[key]=value;
    }
  });
  const until=async predicate=>{
    for(let i=0;i<100;i++){if(predicate())return;await nextTurn();}
    assert.fail("Connector did not settle.");
  };
  const {createConnector}=await import("../frontend/src/connector.js");
  connector=createConnector(()=>{});await connector.start();
  await until(()=>active === "first" && polls.length === 1);
  await nextTurn();
  dispatch({type:"maverick.browser.wake"});
  await until(()=>polls.length === 2);
  assert.equal(polls[1].active_operation_id,"first");
  assert.deepEqual(executed,["first"]);
  releaseFirst();await nextTurn();await nextTurn();
  dispatch({type:"maverick.browser.wake"});
  await until(()=>completed.length === 1);
  assert.deepEqual(executed,["first","second"]);
  assert.deepEqual(completed[0].result,{text:"next observation"});
});
