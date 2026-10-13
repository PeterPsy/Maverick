// Memory-only extension storage survives a Browser document reload, not an
// extension/browser restart. It is never exposed by status or agent commands.
export function createConnectorSession(chrome, currentBinding) {
  let queue=Promise.resolve();
  const transaction=(b,change)=>{
    const run=queue.catch(()=>{}).then(async()=>{
      const current=await currentBinding();
      if(!current || current.sharingId !== b.sharingId)throw new Error("sharing_revoked");
      const {connectorSession:saved}=await chrome.storage.session.get("connectorSession");
      const state=saved?.sharingId === b.sharingId ? saved : {sharingId:b.sharingId,origin:b.connectorFrameOrigin,lease:null,completion:null,backgroundToken:null};
      if(state.origin !== b.connectorFrameOrigin)throw new Error("connector_principal_changed");
      const result=await change(state);
      if((await currentBinding())?.sharingId !== b.sharingId)throw new Error("sharing_revoked");
      return result;
    });
    queue=run;return run;
  };
  const write=state=>chrome.storage.session.set({connectorSession:state});
  return {
    read:b=>transaction(b,state=>({lease:state.lease,completion:state.completion})),
    background:b=>transaction(b,state=>({lease:state.lease,completion:state.completion,backgroundToken:state.backgroundToken})),
    activate:(b,token)=>transaction(b,async state=>{
      if(!state.lease || typeof token !== "string" || !/^[A-Za-z0-9_-]{20,256}$/u.test(token))throw new Error("invalid_background_grant");
      state.backgroundToken=token;await write(state);return {activated:true};
    }),
    save:(b,lease)=>transaction(b,async state=>{
      if(!/^chrome-[a-f0-9-]{36}$/u.test(lease?.connection?.session_id || "") || typeof lease.connector_secret !== "string" || lease.connector_secret.length<20 || lease.connector_secret.length>256)throw new Error("invalid_connector_lease");
      if(state.lease?.connection.session_id !== lease.connection.session_id)state.completion=null;
      state.lease={connection:{session_id:lease.connection.session_id},connector_secret:lease.connector_secret};
      await write(state);return {saved:true};
    }),
    finish:(b,command,result,sessionId)=>transaction(b,async state=>{
      if(!state.lease || state.lease.connection.session_id !== sessionId)return {saved:false};
      state.completion={operation_id:command.operation_id,lease_id:command.lease_id,result};
      try {await write(state);}
      catch {
        state.completion.result={error:"chrome_result_cache_unavailable",detail:"The action finished but its result could not be retained. Do not replay it."};
        await write(state);
      }
      return {saved:true};
    }),
    ack:(b,operationId)=>transaction(b,async state=>{
      if(state.completion?.operation_id === operationId){state.completion=null;await write(state);}
      return {acknowledged:true};
    }),
    clear:()=>{const run=queue.catch(()=>{}).then(()=>chrome.storage.session.remove("connectorSession"));queue=run;return run;},
  };
}
