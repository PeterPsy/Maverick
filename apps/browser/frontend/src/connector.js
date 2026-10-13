import {request,bridge} from "./api.js";
import {stopReason} from "./sharing-state.js";
import {acquireConnectorLease,deliverConnectorCompletion,recoverFrameAuthorization} from "./connector-recovery.js";

// Chrome retains the lease in its trusted memory-only session store. Reloads
// resume it only in the exact actor/workspace app origin; actions never replay.
export function createConnector(report) {
  let lease=null,command=null,timer=null,stopped=true,ticking=false,failures=0;
  let starting=null,generation=0,lastRenewed=0,recovery=false,background=false;
  const revoke=async(error)=>{
    stopped=true;generation++;clearTimeout(timer);
    const previous=lease;lease=null;command=null;
    report(error ? `Sharing stopped: ${error.message}` : "Sharing stopped.","stopped");
    await bridge("stop").catch(()=>{});
    if(previous)await request({action:"companion.disconnect",session_id:previous.connection.session_id,reason:stopReason(error)}).catch(()=>{});
  };
  const fields=()=>({session_id:lease.connection.session_id,connector_secret:lease.connector_secret});
  const deliver=async(next,result,attempt)=>{
    while(attempt===generation && !stopped && lease && Date.now()<next.expires_at*1000) {
      try {
        if(recovery)await deliverConnectorCompletion(fields(),{operation_id:next.operation_id,lease_id:next.lease_id,result});
        else await request({action:"companion.complete",...fields(),operation_id:next.operation_id,lease_id:next.lease_id,result});
        return;
      } catch(error) {
        if(error.status && error.status<500)throw error;
        await new Promise(resolve=>setTimeout(resolve,2000));
      }
    }
  };
  const execute=async next=>{
    const attempt=generation;
    command=next;report(`Running: ${next.action}`);
    try {
      const result=await bridge("execute",next,Math.max(1000,(next.expires_at*1000-Date.now())));
      if(attempt===generation && !stopped && lease)await deliver(next,result,attempt);
    } catch(error) {
      if(attempt===generation && !stopped && lease)await deliver(next,{error:"chrome_observation_failed",detail:error.message},attempt).catch(()=>{});
    } finally {if(command===next)command=null;}
  };
  const tick=async()=>{
    if(stopped || ticking || !lease)return;clearTimeout(timer);ticking=true;
    const attempt=generation;
    let shared;
    try {
      shared=await bridge("status");
      if(attempt!==generation || stopped || !lease)return;
      if(background) {
        report(`Connected in background · ${shared.title || shared.url}${shared.companion_version ? ` · Companion ${shared.companion_version}` : ""}. You can close this Maverick tab.`,"connected");
        return;
      }
      if(recovery && !command && !shared.active_operation) {
        const retained=await bridge("lease.restore");
        if(retained.completion)await deliverConnectorCompletion(fields(),retained.completion);
      }
      const active=command;
      if(active) {
        const operation=await request({action:"operation.get",operation_id:active.operation_id});
        if(attempt!==generation || stopped || !lease)return;
        if(operation.status !== "running")await bridge("cancel",{operation_id:active.operation_id}).catch(()=>{});
        else {
          try {
            await request({action:"companion.progress",...fields(),operation_id:active.operation_id,lease_id:active.lease_id,phase:active.action});
          } catch(error) {
            // Cancellation/completion can win between the status read and progress.
            // Drain the worker without revoking the unrelated connection/queued work.
            if(error.code !== "operation_not_running")throw error;
            await bridge("cancel",{operation_id:active.operation_id}).catch(()=>{});
          }
        }
      }
      if(attempt!==generation || stopped || !lease)return;
      // Cancellation only sets a flag; the worker remains busy while restoring media.
      // Its status also fences a bridge timeout whose local promise already settled.
      const activeOperationId=command?.operation_id || shared.active_operation || null;
      const result=await request({action:"companion.poll",...fields(),url:shared.url,title:shared.title,active_operation_id:activeOperationId});
      if(attempt!==generation || stopped || !lease)return;
      failures=0;
      if(result.command && !activeOperationId)void execute(result.command);
      if(!activeOperationId)report(`Connected · ${shared.title || shared.url}${shared.companion_version ? ` · Companion ${shared.companion_version}` : ""}`,"connected");
      // Maintain the app-frame auth lease independently of shell visibility.
      if(Date.now()-lastRenewed>=60000) {
        lastRenewed=Date.now();
        // Authentication maintenance must never hold up commands/heartbeats.
        void fetch("/.well-known/maverick-app-frame-session",{method:"POST",credentials:"same-origin",cache:"no-store",signal:AbortSignal.timeout(5000)}).catch(()=>{});
      }
    } catch(error) {
      if(attempt!==generation || stopped)return;
      report(error.message);failures++;
      if(error.code === "connection_expired" && recovery && shared) {
        try {
          report("Restoring the agent connection…","recovering");
          const restored=await acquireConnectorLease(shared);
          if(attempt!==generation || stopped) {
            await request({action:"companion.disconnect",session_id:restored.connection.session_id}).catch(()=>{});
            return;
          }
          lease=restored;failures=0;
        } catch(failure){await revoke(failure);}
      } else if([401,403].includes(error.status) && !["connector_unauthorized","actor_required","user_connector_required"].includes(error.code) && failures<10 && recoverFrameAuthorization()) {
        report("Restoring Maverick sign-in…","recovering");
      } else if([401,403,404,409,410].includes(error.status) || /^(connector_scope_required|connector_principal_changed|sharing_revoked|platform_route_unavailable|shared_platform_scope_required|invalid_platform_url|website_scope_required|invalid_website_url|extension_unavailable)/u.test(error.code || error.message) || failures>=10)await revoke(error);
    }
    finally {ticking=false;if(!stopped)timer=setTimeout(tick,3000);}
  };
  window.addEventListener("message",event=>{
    if(event.source === window && event.origin === location.origin && event.data?.type === "maverick.browser.wake")void tick();
  });
  return {
    start() {
      if(starting)return starting;
      if(lease && !stopped)return Promise.resolve(lease.connection);
      const attempt=++generation;
      report("Connecting…","connecting");
      starting=(async()=>{
        const shared=await bridge("status");
        if(attempt!==generation)throw new Error("Sharing was stopped. Connect again to retry.");
        recovery=shared.lease_recovery === true;
        // An authorized background worker owns lease renewal. A reloaded UI
        // must not race it by replacing an expired connection itself.
        const result=shared.background_active ? (await bridge("lease.restore")).lease : await acquireConnectorLease(shared);
        if(!result)throw new Error("Sharing was stopped. Connect again to retry.");
        if(attempt!==generation) {
          await request({action:"companion.disconnect",session_id:result.connection.session_id});
          throw new Error("Sharing was stopped. Connect again to retry.");
        }
        if(shared.background_connector === true) {
          let grant={};
          if(!shared.background_active) {
            const response=await fetch("/.well-known/maverick-app-background/grant",{
              method:"POST",credentials:"same-origin",cache:"no-store",signal:AbortSignal.timeout(10000),
              headers:{"Content-Type":"application/json"},body:JSON.stringify({client_origin:shared.extension_origin,actions:["companion.poll","companion.progress","companion.complete","companion.disconnect","companion.connect","operation.get"]}),
            });
            grant=await response.json();
            if(!response.ok || grant.error)throw new Error("Maverick could not authorize the background connection. Reconnect from Companion.");
          }
          if(attempt!==generation) {
            await request({action:"companion.disconnect",session_id:result.connection.session_id}).catch(()=>{});
            throw new Error("Sharing was stopped. Connect again to retry.");
          }
          await bridge("background.start",grant,20000);background=true;
        }
        lease=result;stopped=false;failures=0;void tick();
        return lease.connection;
      })().catch(error=>{
        if(attempt===generation)report(error.message,"stopped");
        throw error;
      }).finally(()=>{starting=null;});
      return starting;
    },stop:revoke,
  };
}
