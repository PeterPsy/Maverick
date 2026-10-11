import {connectorUrl, connectorOrigins, platformUrl, platformForUrl} from "./scope.mjs";
import {platforms} from "./platforms.mjs";
import {shareableTab, setupError} from "./setup.mjs";
const status = document.querySelector("#status");
const input = document.querySelector("#connector");
const share = document.querySelector("#share");
let selected;
input.value = (await chrome.storage.local.get("connectorUrl")).connectorUrl || "";
try {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  document.querySelector("#tab-title").textContent = tab?.title || "Selected Chrome tab";
  document.querySelector("#tab-url").textContent = tab?.url || "Chrome does not allow this page to be shared.";
  selected = shareableTab(tab); share.disabled = false;
} catch (error) { status.textContent = setupError(error); }
share.onclick = async () => {
  if (!selected || share.disabled) return;
  share.disabled = true;
  try {
    const url = connectorUrl(input.value);
    // Request permissions before any await so Chrome retains the button's user gesture.
    const granted = await chrome.permissions.request({origins: [...connectorOrigins(url), ...platforms[platformForUrl(selected.url)].hosts.map(host=>`https://${host}/*`)]});
    if (!granted) throw new Error("permission_denied");
    // Keep the tab chosen when the popup opened, even if another window gains focus.
    const tab = await chrome.tabs.get(selected.id);
    platformUrl(tab?.url, platformForUrl(selected.url));
    status.textContent = "Opening your Browser connection window…";
    const result = await chrome.runtime.sendMessage({target: "worker", action: "share", tabId: tab.id, url: url.href});
    if (result?.error) throw new Error(result.detail || result.error);
    await chrome.storage.local.set({connectorUrl: url.href});
    status.textContent = "Tab shared. Sign in to Maverick in the Chrome window that opened, then connect the selected tab.";
  } catch (error) { status.textContent = setupError(error); }
  finally { share.disabled = false; }
};
document.querySelector("#stop").onclick = async () => {
  const result = await chrome.runtime.sendMessage({target: "worker", action: "stop"});
  status.textContent = result?.error || "Sharing stopped.";
};
