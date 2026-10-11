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
      throw Object.assign(new Error(result.detail || result.error || `HTTP ${response.status}`), {status: response.status});
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
  if(result?.error)entry.reject(new Error(result.error));else entry.resolve(result);
});
export function bridge(action,command,timeout=5000) {
  const id=crypto.randomUUID();
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error("Browser Companion is unavailable or the command timed out."));},timeout);
    pending.set(id,{resolve,reject,timer});window.postMessage({type:"maverick.browser.request",id,action,command},location.origin);
  });
}
