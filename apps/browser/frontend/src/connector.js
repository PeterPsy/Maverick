import {request,bridge} from "./api.js";

// Secrets stay in this authenticated page's memory. Reloading requires a fresh lease.
export function createConnector(report) {
  let lease=null,command=null,timer=null,stopped=false,ticking=false,failures=0;
  const revoke=async()=>{
    stopped=true;clearTimeout(timer);
    await bridge("stop").catch(()=>{});
    if(lease)await request({action:"companion.disconnect",session_id:lease.connection.session_id}).catch(()=>{});
    lease=null;command=null;report("Condivisione interrotta.");
  };
  const fields=()=>({session_id:lease.connection.session_id,connector_secret:lease.connector_secret});
  const deliver=async(next,result)=>{
    while(!stopped && lease && Date.now()<next.expires_at*1000) {
      try {
        await request({action:"companion.complete",...fields(),operation_id:next.operation_id,lease_id:next.lease_id,result});return;
      } catch(error) {
        if(error.status && error.status<500)throw error;
        await new Promise(resolve=>setTimeout(resolve,2000));
      }
    }
  };
  const execute=async next=>{
    command=next;report(`In corso: ${next.action}`);
    try {
      const result=await bridge("execute",next,Math.max(1000,(next.expires_at*1000-Date.now())));
      if(!stopped && lease)await deliver(next,result);
    } catch(error) {
      if(!stopped && lease)await deliver(next,{error:"chrome_observation_failed",detail:error.message}).catch(()=>{});
    } finally {if(command===next)command=null;}
  };
  const tick=async()=>{
    if(stopped || ticking || !lease)return;clearTimeout(timer);ticking=true;
    try {
      const shared=await bridge("status");
      if(command) {
        const operation=await request({action:"operation.get",operation_id:command.operation_id});
        if(operation.status !== "running") {await bridge("cancel",{operation_id:command.operation_id}).catch(()=>{});command=null;}
        else await request({action:"companion.progress",...fields(),operation_id:command.operation_id,lease_id:command.lease_id,phase:command.action});
      }
      const result=await request({action:"companion.poll",...fields(),url:shared.url,title:shared.title,active_operation_id:command?.operation_id || null});
      failures=0;
      if(result.command && !command)void execute(result.command);
      if(!command)report(`Collegato · ${shared.title || shared.url}`);
      // Maintain the app-frame auth lease independently of shell visibility.
      await fetch("/.well-known/maverick-app-frame-session",{method:"POST",credentials:"same-origin",cache:"no-store"}).catch(()=>{});
    } catch(error) {
      report(error.message);failures++;
      if([401,403,404,409,410].includes(error.status) || /^(connector_scope_required|sharing_revoked|instagram_route_unavailable|extension_unavailable)/u.test(error.message) || failures>=10)await revoke();
    }
    finally {ticking=false;if(!stopped)timer=setTimeout(tick,3000);}
  };
  window.addEventListener("message",event=>{
    if(event.source === window && event.origin === location.origin && event.data?.type === "maverick.browser.wake")void tick();
  });
  return {
    async start() {
      const shared=await bridge("status");
      lease=await request({action:"companion.connect",display_name:shared.title?.slice(0,100) || "Instagram Chrome"});
      stopped=false;report("Collegamento in corso…");void tick();
      return lease.connection;
    },stop:revoke,
  };
}
