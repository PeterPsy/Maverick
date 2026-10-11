import {connectorUrl, connectorOrigins, platformUrl, platformForUrl} from "./scope.mjs";
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
    const granted = await chrome.permissions.request({origins: [...connectorOrigins(url), ...platforms[platformForUrl(tab.url)].hosts.map(host=>`https://${host}/*`)]});
    if (!granted) throw new Error("Permission was not granted.");
    const result = await chrome.runtime.sendMessage({target: "worker", action: "share", tabId: tab.id, url: url.href});
    if (result?.error) throw new Error(result.detail || result.error);
    await chrome.storage.local.set({connectorUrl: url.href});
    status.textContent = "Tab shared. Sign in to Maverick in the Chrome window that opened, then connect the selected tab.";
  } catch (error) { status.textContent = error.message; }
};
document.querySelector("#stop").onclick = async () => {
  const result = await chrome.runtime.sendMessage({target: "worker", action: "stop"});
  status.textContent = result?.error || "Sharing stopped.";
};
