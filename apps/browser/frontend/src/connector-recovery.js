import {request,bridge} from "./api.js";

export async function acquireConnectorLease(shared) {
  const cached=shared.lease_recovery ? await bridge("lease.restore") : {};
  if(cached.lease) {
    const overview=await request({action:"companion.overview"});
    const previous=overview.connections.find(c=>c.session_id === cached.lease.connection.session_id);
    // Never transfer a retained secret to another account or workspace.
    if(!previous || previous.status === "revoked")throw Object.assign(new Error("The connected Loopino account changed. Reconnect from Companion."),{code:"connector_principal_changed"});
    if(previous.expires_at*1000>Date.now())return {...cached.lease,connection:previous};
  }
  const lease=await request({action:"companion.connect",display_name:shared.title?.slice(0,100) || "Shared Chrome tab",allowed_platforms:shared.allowed_platforms || [],agent_tab_id:shared.agent_tab_id,access_mode:shared.access_mode,website_scope:shared.website_scope});
  if(shared.lease_recovery) {
    try {await bridge("lease.store",lease);}
    catch(error) {await request({action:"companion.disconnect",session_id:lease.connection.session_id}).catch(()=>{});throw error;}
  }
  return lease;
}

export function recoverFrameAuthorization() {
  if(window.parent === window || !window.__LOOPINO_PLATFORM_ORIGIN__)return false;
  window.parent.postMessage({type:"loopino.app-frame.authorization-required",path:location.pathname+location.search},window.__LOOPINO_PLATFORM_ORIGIN__);
  return true;
}

export async function deliverConnectorCompletion(fields, completion) {
  try {
    await request({action:"companion.complete",...fields,operation_id:completion.operation_id,lease_id:completion.lease_id,result:completion.result});
  } catch(error) {
    if(error.code !== "operation_not_running")throw error;
    const observed=await request({action:"operation.get",operation_id:completion.operation_id});
    if(!["completed","failed","cancelled","expired"].includes(observed.status))throw error;
  }
  await bridge("completion.ack",{operation_id:completion.operation_id});
}
