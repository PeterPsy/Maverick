import "./style.css";
import {request, bridge} from "./api.js";
import {createConnector} from "./connector.js";
import {createRefreshLoop, isActiveConnection, isPending, overviewDelay} from "./refresh-loop.js";
import {mountShell} from "./shell-view.js";
import {createRecords, label, timestamp} from "./records.js";
import {showResult} from "./result-view.js";
import {createPlatformState} from "./platform-state.js";
import {connectionDetail} from "./sharing-state.js";
import {createAutoConnect} from "./auto-connect.js";
import companionArchiveUrl from "../package/maverick-browser-companion.zip?url";

const launchParams = new URLSearchParams(location.search);
const connectorMode = launchParams.get("connector") === "1";
mountShell(connectorMode);
const $ = selector => document.querySelector(selector);
let platformOrigin = location.origin;
try {
  const supplied = window.__MAVERICK_PLATFORM_ORIGIN__, origin = new URL(supplied);
  if (["http:", "https:"].includes(origin.protocol) && origin.origin === supplied) platformOrigin = origin.origin;
} catch { /* Standalone connector window. */ }
// Chrome signs in through the shell and receives its own fresh isolated frame.
const connectorUrl = new URL("/app/browser?connector=1", platformOrigin);
const frameDomain = location.hostname.match(/^af-[a-f0-9]{24}\.sidecars\.(.+)$/u)?.[1];
if (frameDomain && frameDomain !== connectorUrl.hostname) connectorUrl.searchParams.set("frame_domain", frameDomain);
$("#url").value = connectorUrl.href;
$("#download").href = new URL(companionArchiveUrl, platformOrigin).href;
$("#download").target = "_blank"; $("#download").rel = "noopener noreferrer";
const platform = createPlatformState(platformOrigin, () => {
  if (platform.visible()) void loop.refresh(); else loop.pause();
});

let overview = {connections: [], operations: []}, initialized = false, localSessionId;
function reportError(error) { $("#error").textContent = error.message; $("#error").hidden = false; }
async function run(button, action) {
  if (!action || button.disabled) return;
  const text = button.textContent;
  button.disabled = true; button.setAttribute("aria-busy", "true");
  try { await action.run(); }
  catch (error) { reportError(error); }
  finally { button.disabled = false; button.removeAttribute("aria-busy"); button.textContent = button.dataset.label || text; }
}
const connections = createRecords($("#connections"), run), history = createRecords($("#past-connections"), run), operations = createRecords($("#operations"), run);
function render() {
  const active = overview.connections.filter(connection => connection.sharing_mode === "agent_tab" && isActiveConnection(connection));
  const pending = overview.pending_count ?? overview.operations.filter(isPending).length;
  const current = active.length ? active : overview.connections.filter(connection => connection.sharing_mode === "agent_tab" && connection.status === "offline").slice(0, 1);
  const past = overview.connections.filter(connection => !current.includes(connection));
  const ready = active.some(connection => connection.status === "connected");
  $("#agent-heading").textContent = ready ? "Your agent is ready" : active.length ? "Connecting your agent tab…" : current.length ? "Reconnect your agent tab" : "Give your agent a browser tab";
  const interactive=active.some(connection=>connection.status === "connected" && connection.access_mode === "interactive");
  $("#agent-description").textContent = interactive ? "Ask Maverick to browse, fill a form or interact with a page." : ready ? "Reading is connected. Update Companion to enable browser interactions." : "Open Companion in Chrome and connect your agent tab. Keep it and Maverick open.";
  $("#agent-state").textContent = ready ? "Connected" : active.length ? "Connecting" : current.length ? "Offline" : "Not connected";
  $("#agent-state").className = `badge ${ready ? "state-connected" : ""}`;
  $("#pending-note").hidden = !pending;
  $("#pending-note").textContent = `${pending} ${pending === 1 ? "action" : "actions"} in progress · Follow progress in Activity`;
  const names = new Map(overview.connections.map(connection => [connection.session_id, connection.title || connection.display_name]));
  const connectionRecord = connection => ({
    id: connection.session_id, title: connection.title || connection.display_name,
    status: connection.status,
    detail: connectionDetail(connection),
    action: ["connecting", "connected", "offline"].includes(connection.status) ? {
      label: "Disconnect", run: async () => {
        if (connection.session_id === localSessionId) await connector.stop();
        else await request({action: "companion.disconnect", session_id: connection.session_id});
        await loop.refresh();
      },
    } : null,
  });
  connections(current.map(connectionRecord), "Start with an empty agent tab", "There is no profile or link to choose. Your agent navigates when you ask.");
  history(past.map(connectionRecord), "No previous connections");
  $("#connection-history").hidden = !past.length;
  const query = $("#search").value.trim().toLowerCase(), filter = $("#filter").value;
  const selected = overview.operations.filter(operation => {
    const matches = filter === "all" || (filter === "active" ? isPending(operation) :
      filter === "failed" ? ["failed", "expired"].includes(operation.status) : operation.status === filter);
    return matches && `${label(operation.action)} ${operation.action} ${names.get(operation.session_id) || ""} ${operation.operation_id}`.toLowerCase().includes(query);
  });
  operations(selected.map(operation => ({
    id: operation.operation_id, title: label(operation.action), status: operation.status,
    detail: `${names.get(operation.session_id) || "Shared Chrome tab"} · ${timestamp(operation.created_at)}${operation.progress?.phase ? ` · ${label(operation.progress.phase)}` : ""}`,
    action: isPending(operation) ? {label: "Cancel", run: async () => {
      await request({action: "operation.cancel", operation_id: operation.operation_id}); await loop.refresh();
    }} : {label: "View result", run: async () => showResult(await request({action: "operation.get", operation_id: operation.operation_id}))},
  })), overview.operations.length ? "No matching activity" : "No activity yet",
  overview.operations.length ? "Try another search or filter." : "Your agent's actions and results will appear here.");
  $("#activity-note").textContent = `Showing ${selected.length} of ${overview.operations.length} recent operations. Results expire after about one hour.`;
  if (!initialized) { $("#setup").open = !active.length; initialized = true; }
}

const loop = createRefreshLoop({
  visible: platform.visible,
  async read(signal) {
    const result = await request({action: "companion.overview"}, {signal});
    if (!platform.visible()) return;
    overview = result; render();
    $("#error").hidden = true;
    $("#updated").textContent = `Updated ${new Date().toLocaleTimeString(undefined, {hour: "2-digit", minute: "2-digit"})} · Auto refresh on`;
  },
  delay: () => overviewDelay(overview),
  onError(error) { reportError(error); $("#updated").textContent = "Update failed · Retrying automatically"; },
  onBusy(busy) { $("#refresh").disabled = busy; $("#refresh").setAttribute("aria-busy", String(busy)); },
});

for (const button of document.querySelectorAll("[data-view]")) button.onclick = () => {
  for (const tab of document.querySelectorAll("[data-view]")) {
    if (tab === button) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
    $(`#${tab.dataset.view}-view`).hidden = tab !== button;
  }
  void loop.refresh();
};
$("#search").oninput = render; $("#filter").onchange = render;
$("#refresh").onclick = () => void loop.refresh();
$("#show-setup").onclick = () => {
  document.querySelector('[data-view="tabs"]').click();
  $("#setup").open = true; $("#setup").scrollIntoView({behavior: "instant", block: "start"});
};
$("#copy").onclick = async () => {
  try { await navigator.clipboard.writeText(connectorUrl.href); $("#status").textContent = "Connector address copied."; }
  catch { $("#url").focus(); $("#url").select(); $("#status").textContent = "Select and copy the connector address."; }
};
let connectionState = "stopped", checking, checkAgain = false;
function checkSelectedTab(retry = false) {
  if (["connecting", "connected", "recovering"].includes(connectionState)) return;
  if (checking) { checkAgain ||= retry; return checking; }
  $("#connect").disabled = true;
  checking = bridge("status", undefined, 2500).then(async shared => {
    $("#connect").disabled = false;
    $("#error").hidden = true;
    $("#status").textContent = `Agent tab: ${shared.title || shared.url}${shared.companion_version ? ` · Companion ${shared.companion_version}` : ""}. Ready to connect.`;
    await autoConnect(shared);
  }).catch(error => { $("#status").textContent = error.message; })
    .finally(() => { checking = null; if (checkAgain) { checkAgain = false; void checkSelectedTab(); } });
  return checking;
}
const connector = createConnector((text, state) => {
  if (state) connectionState = state;
  $("#status").textContent = text;
  if (state === "connected" || state === "stopped") {
    $("#connector-actions").hidden = state === "connected";
    $("#connect").disabled = false;
  }
  if (state === "stopped") void loop.refresh();
});
async function connectSelectedTab() {
  const connection = await connector.start(); localSessionId = connection.session_id;
  $("#connector-actions").hidden = true; $("#setup").open = false; await loop.refresh();
}
const autoConnect = createAutoConnect(connectSelectedTab);
$("#connect").onclick = () => run($("#connect"), {run: connectSelectedTab});
function openConnectorSetup(retry = false) {
  $("#connector-actions").hidden = connectionState === "connected";
  void checkSelectedTab(retry);
}
window.addEventListener("message", event => {
  if (event.source === window && event.origin === location.origin && event.data?.type === "maverick.browser.ready") {
    openConnectorSetup(true); return;
  }
  if (event.source !== window.parent || event.origin !== platformOrigin) return;
  const message = event.data;
  if (message?.type === "maverick.app.navigate" && message.app_id === "browser" && ["1", true].includes(message.params?.connector)) {
    openConnectorSetup();
  }
  if (message?.type === "maverick.app.data-changed" && message.owner_app_id === "browser" && ["companion", "state"].includes(message.resource)) void loop.refresh();
});
if (connectorMode) void checkSelectedTab();
window.addEventListener("pagehide", event => { if (event.persisted) loop.pause(); else loop.stop(); });
window.addEventListener("pageshow", event => { if (event.persisted) void loop.refresh(); });
void loop.refresh();
