import test from "node:test";
import assert from "node:assert/strict";
import {createConnectorSession} from "./connector-session.mjs";

function fixture() {
  let b={sharingId:"selected",connectorFrameOrigin:"https://af-selected.sidecars.maverick.test"},saved={};
  const chrome={storage:{session:{async get(){return structuredClone(saved);},async set(value){saved={...saved,...structuredClone(value)};},async remove(key){delete saved[key];}}}};
  return {session:createConnectorSession(chrome,async()=>b),binding:()=>b,replace:value=>{b=value;},saved:()=>saved};
}
const lease={connection:{session_id:"chrome-5394d8de-023e-4e63-acf3-cdc9d56e2aee"},connector_secret:"trusted-session-secret-123456"};

test("a reloaded exact-origin document resumes credentials and one completion without replay",async()=>{
  const f=fixture(),b=f.binding();
  await f.session.save(b,lease);
  await f.session.finish(b,{operation_id:"one",lease_id:"claim"},{performed:true},lease.connection.session_id);
  const resumed=await f.session.read({...b,connectorDocumentId:"reloaded"});
  assert.deepEqual(resumed.lease,lease);assert.equal(resumed.completion.operation_id,"one");
  await f.session.ack(b,"unrelated");assert.equal((await f.session.read(b)).completion.operation_id,"one");
  await f.session.ack(b,"one");assert.equal((await f.session.read(b)).completion,null);
  await f.session.clear();assert.equal(f.saved().connectorSession,undefined);
});

test("sharing replacement, another principal origin and invalid credentials cannot restore a lease",async()=>{
  const f=fixture(),b=f.binding();await f.session.save(b,lease);
  await assert.rejects(f.session.read({...b,connectorFrameOrigin:"https://af-other.sidecars.maverick.test"}),/principal_changed/u);
  await assert.rejects(f.session.save(b,{...lease,connector_secret:"short"}),/invalid_connector_lease/u);
  f.replace({...b,sharingId:"replaced"});await assert.rejects(f.session.read(b),/sharing_revoked/u);
  assert.equal((await f.session.read(f.binding())).lease,null);
});

test("a replaced backend lease discards the old completion and rejects a late result",async()=>{
  const f=fixture(),b=f.binding();await f.session.save(b,lease);
  await f.session.finish(b,{operation_id:"old",lease_id:"claim"},{performed:true},lease.connection.session_id);
  const next={...lease,connection:{session_id:"chrome-6394d8de-023e-4e63-acf3-cdc9d56e2aee"}};
  await f.session.save(b,next);
  assert.equal((await f.session.finish(b,{operation_id:"old",lease_id:"claim"},{performed:true},lease.connection.session_id)).saved,false);
  assert.equal((await f.session.read(b)).completion,null);
});
