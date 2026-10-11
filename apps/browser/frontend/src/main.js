import "./style.css";
import {request, bridge} from "./api.js";
import {createConnector} from "./connector.js";
import {createRefreshLoop, isActiveConnection, isPending, overviewDelay} from "./refresh-loop.js";
import {mountShell} from "./shell-view.js";
import {createRecords, label, timestamp} from "./records.js";
import {showResult} from "./result-view.js";
import {createLab} from "./lab.js";
import {createPlatformState} from "./platform-state.js";
import {connectionDetail} from "./sharing-state.js";
import {createAutoConnect} from "./auto-connect.js";
import companionArchiveUrl from "../package/maverick-browser-companion.zip?url";

const launchParams = new URLSearchParams(location.search);
let connectorMode = launchParams.get("connector") === "1";
mountShell(connectorMode);
const $ = selector => document.querySelector(selector);
let platformOrigin = location.origin;
try {
  const supplied = window.__MAVERICK_PLATFORM_ORIGIN__, origin = new URL(supplied);
  if (["http:", "https:"].includes(origin.protocol) && origin.origin === supplied) platformOrigin = origin.origin;
} catch { /* Standalone connector window. */ }
$("#connectors-link").href = new URL("/app/platform-connectors", platformOrigin).href;
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

let overview = {connections: [], operations: []}, view = "tabs", initialized = false;
function reportError(error) { $("#error").textContent = error.message; $("#error").hidden = false; }
async function run(button, action) {
  if (!action || button.disabled) return;
  const text = button.textContent;
  button.disabled = true; button.setAttribute("aria-busy", "true");
  try { await action.run(); }
  catch (error) { reportError(error); }
  finally { button.disabled = false; button.removeAttribute("aria-busy"); button.textContent = button.dataset.label || text; }
}
const connections = createRecords($("#connections"), run), operations = createRecords($("#operations"), run);
function render() {
  const active = overview.connections.filter(isActiveConnection);
  $("#tab-count").textContent = active.length;
  $("#pending-count").textContent = overview.pending_count ?? overview.operations.filter(isPending).length;
  $("#activity-count").textContent = overview.operations.length;
  const names = new Map(overview.connections.map(connection => [connection.session_id, connection.title || connection.display_name]));
  connections(overview.connections.map(connection => ({
    id: connection.session_id, title: connection.title || connection.display_name,
    status: connection.status,
    detail: connectionDetail(connection),
    action: ["connecting", "connected", "offline"].includes(connection.status) ? {
      label: "Stop sharing", run: async () => {
        await request({action: "companion.disconnect", session_id: connection.session_id});
        await loop.refresh();
      },
    } : null,
  })), "No shared tabs yet", "Connect Chrome above to share your first platform tab.");
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
  overview.operations.length ? "Try another search or filter." : "Observations from your shared tabs will appear here.");
  $("#activity-note").textContent = `Showing ${selected.length} of ${overview.operations.length} recent operations. Results expire after about one hour.`;
  if (!initialized) { $("#setup").open = connectorMode || !active.length; initialized = true; }
}

const lab = createLab(run);
const loop = createRefreshLoop({
  visible: platform.visible,
  async read(signal) {
    const result = await request({action: "companion.overview"}, {signal});
    if (!platform.visible()) return;
    overview = result; render();
    $("#error").hidden = true;
    $("#updated").textContent = `Updated ${new Date().toLocaleTimeString(undefined, {hour: "2-digit", minute: "2-digit"})} · Auto refresh on`;
    if (view === "lab") await lab.refresh(signal);
  },
  delay: () => view === "lab" ? 30000 : overviewDelay(overview),
  onError(error) { reportError(error); $("#updated").textContent = "Update failed · Retrying automatically"; },
  onBusy(busy) { $("#refresh").disabled = busy; $("#refresh").setAttribute("aria-busy", String(busy)); },
});

for (const button of document.querySelectorAll("[data-view]")) button.onclick = () => {
  view = button.dataset.view;
  for (const tab of document.querySelectorAll("[data-view]")) {
    if (tab === button) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
    $(`#${tab.dataset.view}-view`).hidden = tab !== button;
  }
  void loop.refresh();
};
$("#search").oninput = render; $("#filter").onchange = render;
$("#refresh").onclick = () => void loop.refresh();
$("#copy").onclick = async () => {
  try { await navigator.clipboard.writeText(connectorUrl.href); $("#status").textContent = "Connector address copied."; }
  catch { $("#url").focus(); $("#url").select(); $("#status").textContent = "Select and copy the connector address."; }
};
let connectionState = "stopped", checking, checkAgain = false;
function checkSelectedTab(retry = false) {
  if (["connecting", "connected"].includes(connectionState)) return;
  if (checking) { checkAgain ||= retry; return checking; }
  $("#connect").disabled = true;
  checking = bridge("status", undefined, 2500).then(async shared => {
    $("#connect").disabled = false;
    $("#error").hidden = true;
    $("#status").textContent = `Selected tab: ${shared.title || shared.url}${shared.companion_version ? ` · Companion ${shared.companion_version}` : ""}. Ready to connect.`;
    await autoConnect(shared);
  }).catch(error => { $("#status").textContent = error.message; })
    .finally(() => { checking = null; if (checkAgain) { checkAgain = false; void checkSelectedTab(); } });
  return checking;
}
const connector = createConnector((text, state) => {
  if (state) connectionState = state;
  $("#status").textContent = text;
  if (state === "connected" || state === "stopped") {
    $("#stop").hidden = state !== "connected";
    $("#connect").hidden = state === "connected";
    $("#connect").disabled = false;
  }
  if (state === "stopped") void loop.refresh();
});
async function connectSelectedTab() {
  await connector.start(); $("#connect").hidden = true; $("#stop").hidden = false; await loop.refresh();
}
const autoConnect = createAutoConnect(connectSelectedTab);
$("#connect").onclick = () => run($("#connect"), {run: connectSelectedTab});
$("#stop").onclick = () => run($("#stop"), {run: async () => { await connector.stop(); await loop.refresh(); }});
function openConnectorSetup(retry = false) {
  connectorMode = true; $("#setup").open = true; $("#connector-actions").hidden = false;
  $("#setup summary strong").textContent = "Connect your selected tab";
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
