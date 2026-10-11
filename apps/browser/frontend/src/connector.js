import {request,bridge} from "./api.js";

// Secrets stay in this authenticated page's memory. Reloading requires a fresh lease.
export function createConnector(report) {
  let lease=null,command=null,timer=null,stopped=true,ticking=false,failures=0;
  let starting=null,generation=0,lastRenewed=0;
  const revoke=async()=>{
    stopped=true;generation++;clearTimeout(timer);
    const previous=lease;lease=null;command=null;
    report("Sharing stopped.","stopped");
    await bridge("stop").catch(()=>{});
    if(previous)await request({action:"companion.disconnect",session_id:previous.connection.session_id}).catch(()=>{});
  };
  const fields=()=>({session_id:lease.connection.session_id,connector_secret:lease.connector_secret});
  const deliver=async(next,result,attempt)=>{
    while(attempt===generation && !stopped && lease && Date.now()<next.expires_at*1000) {
      try {
        await request({action:"companion.complete",...fields(),operation_id:next.operation_id,lease_id:next.lease_id,result});return;
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
    try {
      const shared=await bridge("status");
      if(attempt!==generation || stopped || !lease)return;
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
      if(!activeOperationId)report(`Connected · ${shared.title || shared.url}`,"connected");
      // Maintain the app-frame auth lease independently of shell visibility.
      if(Date.now()-lastRenewed>=60000) {
        lastRenewed=Date.now();
        await fetch("/.well-known/maverick-app-frame-session",{method:"POST",credentials:"same-origin",cache:"no-store"}).catch(()=>{});
      }
    } catch(error) {
      if(attempt!==generation || stopped)return;
      report(error.message);failures++;
      if([401,403,404,409,410].includes(error.status) || /^(connector_scope_required|sharing_revoked|platform_route_unavailable|extension_unavailable)/u.test(error.message) || failures>=10)await revoke();
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
        const result=await request({action:"companion.connect",display_name:shared.title?.slice(0,100) || "Shared Chrome tab"});
        if(attempt!==generation) {
          await request({action:"companion.disconnect",session_id:result.connection.session_id});
          throw new Error("Sharing was stopped. Connect again to retry.");
        }
        lease=result;stopped=false;failures=0;void tick();
        return lease.connection;
      })().finally(()=>{starting=null;});
      return starting;
    },stop:revoke,
  };
}
