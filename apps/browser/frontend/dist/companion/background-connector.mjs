// The offscreen capture document wakes this loop. Credentials remain in the
// worker's trusted session store; no website or offscreen page receives them.
export function createBackgroundConnector({binding,session,status,execute,cancel,stop,fetch:request=globalThis.fetch}) {
  let ticking=false,active=null;
  const call=async(b,grant,body,method="POST")=>{
    const response=await request(new URL("/.well-known/maverick-app-background/request",b.connectorFrameOrigin),{
      method,credentials:"omit",cache:"no-store",redirect:"error",signal:AbortSignal.timeout(method === "DELETE" || body?.action === "companion.disconnect" ? 3000 : 15000),
      headers:{"Content-Type":"application/json",Authorization:`Bearer ${grant}`},...(method === "POST" ? {body:JSON.stringify(body)} : {}),
    });
    const result=await response.json();
    if(!response.ok || result.error)throw Object.assign(new Error(result.detail || result.error),{code:result.error,status:response.status});
    return result;
  };
  const fields=lease=>({session_id:lease.connection.session_id,connector_secret:lease.connector_secret});
  const deliver=async(b,saved)=>{
    const completion=saved.completion;
    if(!completion)return;
    try {await call(b,saved.backgroundToken,{action:"companion.complete",...fields(saved.lease),...completion});}
    catch(error) {
      if(error.code !== "operation_not_running")throw error;
      const result=await call(b,saved.backgroundToken,{action:"operation.get",operation_id:completion.operation_id});
      if(!["completed","failed","cancelled","expired"].includes(result.status))throw error;
    }
    await session.ack(b,completion.operation_id);
  };
  async function tick() {
    if(ticking)return;ticking=true;
    let b;
    try {
      b=await binding();if(!b)return;
      const saved=await session.background(b);if(!saved.backgroundToken || !saved.lease)return;
      const shared=await status(b);
      if(active && active.sharingId !== b.sharingId)active=null;
      if(active) {
        const operation=await call(b,saved.backgroundToken,{action:"operation.get",operation_id:active.command.operation_id});
        if(operation.status !== "running")cancel(active.command.operation_id);
        else try {await call(b,saved.backgroundToken,{action:"companion.progress",...fields(saved.lease),operation_id:active.command.operation_id,lease_id:active.command.lease_id,phase:active.command.action});}
        catch(error){if(error.code !== "operation_not_running")throw error;cancel(active.command.operation_id);}
      } else if(!shared.active_operation)await deliver(b,saved);
      const activeId=active?.command.operation_id || shared.active_operation || null;
      let result;
      try {result=await call(b,saved.backgroundToken,{action:"companion.poll",...fields(saved.lease),url:shared.url,title:shared.title,active_operation_id:activeId});}
      catch(error) {
        if(error.code !== "connection_expired")throw error;
        if(activeId)cancel(activeId);
        const next=await call(b,saved.backgroundToken,{action:"companion.connect",display_name:shared.title?.slice(0,100) || "Shared Chrome tab",allowed_platforms:b.allowedPlatforms,agent_tab_id:b.agentTabId,access_mode:b.accessMode,website_scope:b.websiteScope});
        if((await binding())?.sharingId !== b.sharingId) {
          await call(b,saved.backgroundToken,{action:"companion.disconnect",session_id:next.connection.session_id}).catch(()=>{});return;
        }
        await session.save(b,next);return;
      }
      if((await binding())?.sharingId !== b.sharingId)return;
      if(result.command && !activeId) {
        const task={sharingId:b.sharingId,command:result.command};active=task;
        // Execute once. Retained completion is drained by a later tick; network
        // retry and worker suspension never replay a claimed interaction.
        void execute(b,result.command).catch(()=>{}).finally(()=>{if(active===task)active=null;});
      }
    } catch(error) {
      if(b && ([401,403,404,410].includes(error.status) || /^(sharing_revoked|invalid_website_url|website_scope_required|tab_capture_unavailable)$/u.test(error.message)))await stop(error.code || error.message,b.sharingId);
      // Network/server failures leave sharing bound; the next wake retries reads
      // and retained results, never the action itself.
    } finally {ticking=false;}
  }
  return {tick,async disconnect(b,reason="sharing_stopped",retained) {
    const saved=retained || await session.background(b);
    if(!saved.backgroundToken)return;
    const diagnostic=reason === "sharing_stopped" ? "user_stopped" : reason === "connection_replaced" ? reason : reason.includes("scope") || reason === "tab_left_platform_scope" ? "platform_route_unavailable" : "sharing_revoked";
    if(saved.lease)await call(b,saved.backgroundToken,{action:"companion.disconnect",session_id:saved.lease.connection.session_id,reason:diagnostic}).catch(()=>{});
    await call(b,saved.backgroundToken,null,"DELETE").catch(()=>{});
  }};
}
