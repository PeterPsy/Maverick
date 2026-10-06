import {connectorUrl, instagramUrl} from "./scope.mjs";
const status = document.querySelector("#status");
const input = document.querySelector("#connector");
input.value = (await chrome.storage.local.get("connectorUrl")).connectorUrl || "";
document.querySelector("#share").onclick = async () => {
  try {
    const url = connectorUrl(input.value);
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    instagramUrl(tab?.url);
    // Optional host access is granted by this user gesture, never by an agent.
    const granted = await chrome.permissions.request({origins: [url.origin + "/*", "https://www.instagram.com/*"]});
    if (!granted) throw new Error("Permesso non concesso.");
    const result = await chrome.runtime.sendMessage({target: "worker", action: "share", tabId: tab.id, url: url.href});
    if (result?.error) throw new Error(result.detail || result.error);
    await chrome.storage.local.set({connectorUrl: url.href});
    status.textContent = "Scheda condivisa. Completa il collegamento nella finestra Browser aperta.";
  } catch (error) { status.textContent = error.message; }
};
document.querySelector("#stop").onclick = async () => {
  const result = await chrome.runtime.sendMessage({target: "worker", action: "stop"});
  status.textContent = result?.error || "Condivisione interrotta.";
};
