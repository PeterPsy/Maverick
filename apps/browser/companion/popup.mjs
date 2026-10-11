import {connectorUrl, platformForUrl} from "./scope.mjs";
import {shareableTab, setupError, defaultConnectorUrl} from "./setup.mjs";
const status = document.querySelector("#status");
const input = document.querySelector("#connector");
const share = document.querySelector("#share");
let selected;
input.value = (await chrome.storage.local.get("connectorUrl")).connectorUrl || defaultConnectorUrl;
const showDestination = () => {
  try {document.querySelector("#destination").textContent = `Connects to ${connectorUrl(input.value).host}`;}
  catch {document.querySelector("#destination").textContent = "Check Connection settings below";}
};
showDestination(); input.oninput = showDestination;
try {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  document.querySelector("#tab-title").textContent = tab?.title || "Selected Chrome tab";
  document.querySelector("#tab-url").textContent = tab?.url || "Chrome does not allow this page to be shared.";
  selected = shareableTab(tab, chrome.runtime.getURL("agent-tab.html")); share.disabled = false;
  if (selected.allowed_platforms) {
    share.textContent = "Connect agent tab";
    document.querySelector("#tab-url").textContent = "Starts empty · navigation across six supported platforms";
  }
} catch (error) { status.textContent = setupError(error); }
share.onclick = async () => {
  if (!selected || share.disabled) return;
  share.disabled = true;
  try {
    const url = connectorUrl(input.value);
    status.textContent = "Allow Chrome access if asked. Connecting to Maverick…";
    // Send before any await. The worker retains the transaction if this popup closes.
    const result = await chrome.runtime.sendMessage({target: "worker", action: "share", tabId: selected.id, url: url.href, agentTab: Boolean(selected.allowed_platforms), platform: platformForUrl(selected.url), reuseConnector: document.querySelector("#reuse").checked});
    if (result?.error) throw new Error(result.detail || result.error);
    status.textContent = "Connecting in Maverick. Sign in there if asked; the shared tab connects automatically. Keep both tabs open.";
  } catch (error) { status.textContent = setupError(error); }
  finally { share.disabled = false; }
};
document.querySelector("#open-agent").onclick = async () => {
  const result = await chrome.runtime.sendMessage({target:"worker", action:"agent.open"});
  if (result?.error) status.textContent = setupError(new Error(result.error));
};
document.querySelector("#stop").onclick = async () => {
  const result = await chrome.runtime.sendMessage({target: "worker", action: "stop"});
  status.textContent = result?.error || "Sharing stopped.";
};
