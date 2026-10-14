// Injected only into the exact Browser document selected through the extension popup.
if (!globalThis.loopinoBrowserBridgeInstalled) {
  globalThis.loopinoBrowserBridgeInstalled = true;
  chrome.runtime.onMessage.addListener((message,sender)=>{
    if(sender.id === chrome.runtime.id && message.target === "connector" && message.action === "wake")window.postMessage({type:"loopino.browser.wake"},location.origin);
  });
  window.addEventListener("message", async event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.type !== "loopino.browser.request") return;
    const {id, action, command} = event.data;
    if (typeof id !== "string" || id.length > 80 || !["status", "execute", "stop", "cancel", "lease.store", "lease.restore", "completion.ack", "background.start"].includes(action)) return;
    try {
      const result = await chrome.runtime.sendMessage({target: "worker", action, command});
      window.postMessage({type: "loopino.browser.response", id, result}, location.origin);
    } catch (error) {
      window.postMessage({type: "loopino.browser.response", id, result: {error: "extension_unavailable", detail: String(error.message).slice(0,300)}}, location.origin);
    }
  });
}
window.postMessage({type:"loopino.browser.ready"},location.origin);
