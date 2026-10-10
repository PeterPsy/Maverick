import {connectorUrl, platformUrl, platformForUrl} from "./scope.mjs";
import {platforms} from "./platforms.mjs";
const status = document.querySelector("#status");
const input = document.querySelector("#connector");
input.value = (await chrome.storage.local.get("connectorUrl")).connectorUrl || "";
document.querySelector("#share").onclick = async () => {
  try {
    const url = connectorUrl(input.value);
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    platformUrl(tab?.url);
    // Optional host access is granted by this user gesture, never by an agent.
    const granted = await chrome.permissions.request({origins: [url.origin + "/*", ...platforms[platformForUrl(tab.url)].hosts.map(host=>`https://${host}/*`)]});
    if (!granted) throw new Error("Permission was not granted.");
    const result = await chrome.runtime.sendMessage({target: "worker", action: "share", tabId: tab.id, url: url.href});
    if (result?.error) throw new Error(result.detail || result.error);
    await chrome.storage.local.set({connectorUrl: url.href});
    status.textContent = "Tab shared. Complete the connection in the Browser window that opened.";
  } catch (error) { status.textContent = error.message; }
};
document.querySelector("#stop").onclick = async () => {
  const result = await chrome.runtime.sendMessage({target: "worker", action: "stop"});
  status.textContent = result?.error || "Sharing stopped.";
};
