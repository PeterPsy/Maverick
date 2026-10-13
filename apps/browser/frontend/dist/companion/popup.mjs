import {connectorUrl} from "./scope.mjs";
import {selectedAgentTab, setupError, defaultConnectorUrl} from "./setup.mjs";
const status = document.querySelector("#status");
const input = document.querySelector("#connector");
const share = document.querySelector("#share");
const openAgent = document.querySelector("#open-agent");
let selected;
document.querySelector("#version").textContent = chrome.runtime.getManifest().version;
const report = (text, state = "info") => { status.textContent = text; status.dataset.state = state; };
input.value = (await chrome.storage.local.get("connectorUrl")).connectorUrl || defaultConnectorUrl;
const showDestination = () => {
  try {document.querySelector("#destination").textContent = `Connects to ${connectorUrl(input.value).host}`;}
  catch {document.querySelector("#destination").textContent = "Check Connection settings below";}
};
showDestination(); input.oninput = showDestination;
try {
  const {binding, agentTab} = await chrome.storage.session.get(["binding", "agentTab"]);
  document.querySelector("#stop").hidden = !binding;
  if (agentTab) {
    document.querySelector("#tab-title").textContent = "Your agent tab is open";
    document.querySelector("#tab-url").textContent = "Return to the tab your agent uses to view it or reconnect.";
  }
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  selected = selectedAgentTab(tab, chrome.runtime.getURL("agent-tab.html"), agentTab);
  document.querySelector("#tab-title").textContent = selected.reconnect ? selected.title : "Your agent’s browser";
  document.querySelector("#tab-url").textContent = selected.url || "Starts empty. Maverick chooses pages when you ask.";
  document.querySelector("#share-label").textContent = selected.reconnect ? "Reconnect agent tab" : "Connect agent tab";
  share.hidden = false; share.disabled = false;
  openAgent.hidden = true;
} catch (error) {
  if (!["agent_tab_required", "active_tab_unavailable"].includes(error.message)) report(setupError(error), "error");
}
share.onclick = async () => {
  if (!selected || share.disabled) return;
  share.disabled = true;
  share.setAttribute("aria-busy", "true");
  try {
    const url = connectorUrl(input.value);
    report("Allow Chrome access if asked. Connecting to Maverick…");
    // Send before any await. The worker retains the transaction if this popup closes.
    const result = await chrome.runtime.sendMessage({target: "worker", action: "share", tabId: selected.id, url: url.href, agentTab: true, reuseConnector: document.querySelector("#reuse").checked});
    if (result?.error) throw new Error(result.detail || result.error);
    report(result.background ? "Connected in background. Keep the agent tab open; Maverick can stay closed." : "Connecting in Maverick. Sign in there if asked; once connected, you can close that Maverick tab. Keep the agent tab open.");
    document.querySelector("#stop").hidden = false;
  } catch (error) { report(setupError(error), "error"); }
  finally { share.disabled = false; share.removeAttribute("aria-busy"); }
};
openAgent.onclick = async () => {
  const result = await chrome.runtime.sendMessage({target:"worker", action:"agent.open"});
  if (result?.error) report(setupError(new Error(result.error)), "error");
};
document.querySelector("#stop").onclick = async () => {
  const result = await chrome.runtime.sendMessage({target: "worker", action: "stop"});
  report(result?.error || "Agent tab disconnected.", result?.error ? "error" : "info");
  if (!result?.error) document.querySelector("#stop").hidden = true;
};
