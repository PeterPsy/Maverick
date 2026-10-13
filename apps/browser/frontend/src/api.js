export async function request(body, {signal, timeoutMs = 30000} = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, {once: true});
  const timer = setTimeout(abort, timeoutMs);
  try {
    const response = await fetch("/api/apps/browser/backend", {
      method: "POST", credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });
    let result;
    try { result = await response.json(); }
    catch { throw Object.assign(new Error("Browser returned an unreadable response. Please retry."), {status: response.status}); }
    if (!response.ok || result.error) {
      throw Object.assign(new Error(result.detail || result.error || `HTTP ${response.status}`), {status: response.status, code: result.error});
    }
    return result;
  } catch (error) {
    if (controller.signal.aborted && !signal?.aborted) throw new Error("Browser did not respond in time. Please retry.");
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

const pending=new Map();
window.addEventListener("message",event=>{
  if(event.source !== window || event.origin !== location.origin || event.data?.type !== "maverick.browser.response")return;
  const entry=pending.get(event.data.id);if(!entry)return;
  pending.delete(event.data.id);clearTimeout(entry.timer);
  const result=event.data.result;
  if(result?.error) {
    const guidance = ["connector_scope_required", "sharing_revoked"].includes(result.error)
      ? "Open Companion in Chrome, choose Open agent tab, then connect it from the extension toolbar. Keep the agent tab open; Maverick is needed for initial authorization."
      : result.detail || result.error;
    entry.reject(Object.assign(new Error(guidance),{code:result.error}));
  } else entry.resolve(result);
});
export function bridge(action,command,timeout=5000) {
  const id=crypto.randomUUID();
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{
      pending.delete(id);
      const message=action === "status"
        ? "No agent tab is attached to this window. In Companion, choose Open agent tab, then connect it from the extension toolbar."
        : "The Chrome command timed out. Keep the shared tab open and check the connection in Companion. Poll the existing operation before retrying an action.";
      reject(Object.assign(new Error(message),{code:action === "status" ? "companion_unavailable" : "companion_command_timeout"}));
    },timeout);
    pending.set(id,{resolve,reject,timer});window.postMessage({type:"maverick.browser.request",id,action,command},location.origin);
  });
}
