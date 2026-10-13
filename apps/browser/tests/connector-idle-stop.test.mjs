import test from "node:test";
import assert from "node:assert/strict";
import {setImmediate as nextTurn} from "node:timers/promises";

test("Disconnect revokes a replacement lease whose acknowledgement arrives late",async t=>{
  const origin="https://af-browser.sidecars.maverick.test",listeners=[],calls=[];
  const previous={window:globalThis.window,location:globalThis.location};
  let cached=null,expired=false,serial=0,lateStore,connector;
  globalThis.location={origin};
  const dispatch=data=>listeners.forEach(listener=>listener({source:window,origin,data}));
  globalThis.window={addEventListener(_type,listener){listeners.push(listener);},postMessage(message){
    if(message.action === "lease.store") {
      cached=message.command;
      if(serial === 2){lateStore=message;return;}
    }
    const result=message.action === "status" ? {lease_recovery:true,title:"Test tab"} : message.action === "lease.restore" ? {lease:cached} : {};
    if(message.action === "stop")cached=null;
    queueMicrotask(()=>dispatch({type:"maverick.browser.response",id:message.id,result}));
  }};
  t.mock.method(globalThis,"fetch",async(_url,options)=>{
    const body=options.body ? JSON.parse(options.body) : {};calls.push(body);
    const value=body.action === "companion.connect" ? {connection:{session_id:`session-${++serial}`},connector_secret:"private"}
      : body.action === "companion.overview" ? {connections:[{session_id:"session-1",status:"offline",expires_at:Date.now()/1000-1}]}
      : body.action === "companion.poll" && expired ? {error:"connection_expired"} : {};
    return {ok:!value.error,status:value.error ? 410 : 200,async json(){return value;}};
  });
  t.after(async()=>{
    if(lateStore)dispatch({type:"maverick.browser.response",id:lateStore.id,result:{saved:true}});
    await connector?.stop();
    for(const [key,value] of Object.entries(previous)){if(value === undefined)delete globalThis[key];else globalThis[key]=value;}
  });
  const until=async predicate=>{for(let i=0;i<100;i++){if(predicate())return;await nextTurn();}assert.fail("Connector did not settle");};
  const {createConnector}=await import("../frontend/src/connector.js");
  connector=createConnector(()=>{});await connector.start();
  await until(()=>calls.some(c=>c.action === "companion.poll"));await nextTurn();
  expired=true;dispatch({type:"maverick.browser.wake"});await until(()=>lateStore);
  await connector.stop();
  dispatch({type:"maverick.browser.response",id:lateStore.id,result:{saved:true}});
  await until(()=>calls.some(c=>c.action === "companion.disconnect" && c.session_id === "session-2"));
});
