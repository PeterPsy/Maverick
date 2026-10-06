export async function request(body) {
  const response=await fetch("/api/apps/browser/backend",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok || result.error)throw Object.assign(new Error(result.detail || result.error || `HTTP ${response.status}`),{status:response.status});
  return result;
}

const pending=new Map();
window.addEventListener("message",event=>{
  if(event.source !== window || event.origin !== location.origin || event.data?.type !== "maverick.browser.response")return;
  const entry=pending.get(event.data.id);if(!entry)return;
  pending.delete(event.data.id);clearTimeout(entry.timer);
  const result=event.data.result;
  if(result?.error)entry.reject(new Error(result.error));else entry.resolve(result);
});
export function bridge(action,command,timeout=5000) {
  const id=crypto.randomUUID();
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error("Estensione non collegata o comando scaduto."));},timeout);
    pending.set(id,{resolve,reject,timer});window.postMessage({type:"maverick.browser.request",id,action,command},location.origin);
  });
}
