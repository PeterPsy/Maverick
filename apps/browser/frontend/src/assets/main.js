const BACKEND_URL = "/api/apps/browser/backend";
const DEV_MODE = "maverick_dev_inspector";

const state = {
  status: null,
  sessions: [],
  activeSessionId: "",
  lastPolicy: null,
  activePane: "snapshot-pane",
  busy: false,
};

const elements = {
  app: document.querySelector(".browser-app"),
  brokerSummary: document.querySelector("#broker-summary"),
  brokerStatus: document.querySelector("#broker-status"),
  sessionCount: document.querySelector("#session-count"),
  auditCount: document.querySelector("#audit-count"),
  policyStatus: document.querySelector("#policy-status"),
  policyDetails: document.querySelector("#policy-details"),
  urlForm: document.querySelector("#url-form"),
  urlInput: document.querySelector("#url-input"),
  modeInput: document.querySelector("#mode-input"),
  preflightButton: document.querySelector("#preflight-button"),
  navigateButton: document.querySelector("#navigate-button"),
  newSessionButton: document.querySelector("#new-session-button"),
  closeSessionButton: document.querySelector("#close-session-button"),
  sessionPicker: document.querySelector("#session-picker"),
  sessionSummary: document.querySelector("#session-summary"),
  sessionList: document.querySelector("#session-list"),
  refreshTabsButton: document.querySelector("#refresh-tabs-button"),
  tabSummary: document.querySelector("#tab-summary"),
  tabList: document.querySelector("#tab-list"),
  snapshotButton: document.querySelector("#snapshot-button"),
  screenshotButton: document.querySelector("#screenshot-button"),
  consoleButton: document.querySelector("#console-button"),
  networkButton: document.querySelector("#network-button"),
  waitButton: document.querySelector("#wait-button"),
  waitState: document.querySelector("#wait-state"),
  fullPageInput: document.querySelector("#full-page-input"),
  snapshotMeta: document.querySelector("#snapshot-meta"),
  snapshotOutput: document.querySelector("#snapshot-output"),
  refsSummary: document.querySelector("#refs-summary"),
  refsList: document.querySelector("#refs-list"),
  refInput: document.querySelector("#ref-input"),
  typeInput: document.querySelector("#type-input"),
  clickButton: document.querySelector("#click-button"),
  typeButton: document.querySelector("#type-button"),
  pressKeyButton: document.querySelector("#press-key-button"),
  screenshotMeta: document.querySelector("#screenshot-meta"),
  screenshotFrame: document.querySelector("#screenshot-frame"),
  consoleMeta: document.querySelector("#console-meta"),
  consoleList: document.querySelector("#console-list"),
  networkMeta: document.querySelector("#network-meta"),
  networkList: document.querySelector("#network-list"),
  auditButton: document.querySelector("#audit-button"),
  auditMeta: document.querySelector("#audit-meta"),
  auditList: document.querySelector("#audit-list"),
  messageRegion: document.querySelector("#message-region"),
};

function unwrapPayload(payload) {
  return payload?.json && typeof payload.json === "object" ? payload.json : payload;
}

async function callBackend(body) {
  const response = await fetch(BACKEND_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error(`Backend returned a non-JSON response (${response.status}).`);
  }
  const statusCode = Number(payload?.status_code || response.status || 200);
  const result = unwrapPayload(payload);
  if (!response.ok || statusCode >= 400) {
    const message = result?.detail || result?.error || `Browser backend failed with ${statusCode}.`;
    const backendError = new Error(message);
    backendError.payload = result;
    backendError.statusCode = statusCode;
    throw backendError;
  }
  return result;
}

function activeSession() {
  return state.sessions.find((session) => session.session_id === state.activeSessionId) || null;
}

function activeMode() {
  const session = activeSession();
  return session?.mode || elements.modeInput.value || "read_only";
}

function currentTargetUrl() {
  const session = activeSession();
  return session?.url && session.url !== "about:blank" ? session.url : elements.urlInput.value.trim();
}

function setBusy(isBusy) {
  state.busy = isBusy;
  document.querySelectorAll("button, select, input").forEach((control) => {
    control.disabled = isBusy;
  });
  updateControls();
}

function setMessage(message, tone = "info") {
  elements.messageRegion.textContent = message || "";
  elements.messageRegion.dataset.tone = tone;
}

function clearMessage() {
  setMessage("");
}

function setPane(paneId) {
  state.activePane = paneId;
  document.querySelectorAll(".pane-tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.pane === paneId);
  });
  document.querySelectorAll(".pane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === paneId);
  });
}

function shortId(value) {
  return value ? `${value.slice(0, 8)}...${value.slice(-4)}` : "No session";
}

function renderStatus(status) {
  state.status = status;
  state.sessions = Array.isArray(status.sessions) ? status.sessions : [];
  if (!state.sessions.some((session) => session.session_id === state.activeSessionId)) {
    state.activeSessionId = state.sessions[0]?.session_id || "";
  }

  const broker = status.broker || {};
  const brokerState = broker.status || "unknown";
  elements.brokerStatus.textContent = brokerState;
  elements.brokerStatus.dataset.state = brokerState;
  elements.brokerSummary.textContent = `${broker.provider || "playwright_lab"}: ${brokerState}`;
  elements.sessionCount.textContent = String(status.session_count || state.sessions.length || 0);
  elements.auditCount.textContent = String(status.audit_count || 0);

  renderSessions();
  renderTabs(activeSession()?.tabs || []);
  updateControls();
}

function renderSessions() {
  elements.sessionPicker.innerHTML = "";
  elements.sessionPicker.append(optionElement("", "No session"));
  state.sessions.forEach((session) => {
    const label = `${shortId(session.session_id)} - ${session.mode || "read_only"}`;
    elements.sessionPicker.append(optionElement(session.session_id, label));
  });
  elements.sessionPicker.value = state.activeSessionId;

  const session = activeSession();
  elements.sessionSummary.textContent = session
    ? `${session.mode || "read_only"} - ${session.title || session.url || "about:blank"}`
    : "No active session";
  elements.sessionList.innerHTML = "";
  if (!state.sessions.length) {
    elements.sessionList.append(emptyElement("No broker sessions yet."));
    return;
  }
  state.sessions.forEach((item) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "session-row";
    row.classList.toggle("active", item.session_id === state.activeSessionId);
    row.innerHTML = `
      <span>${escapeHtml(shortId(item.session_id))}</span>
      <strong>${escapeHtml(item.mode || "read_only")}</strong>
      <small>${escapeHtml(item.title || item.url || "about:blank")}</small>
    `;
    row.addEventListener("click", () => {
      state.activeSessionId = item.session_id;
      elements.sessionPicker.value = state.activeSessionId;
      renderSessions();
      renderTabs(item.tabs || []);
      updateControls();
    });
    elements.sessionList.append(row);
  });
}

function renderTabs(tabs) {
  const items = Array.isArray(tabs) ? tabs : [];
  elements.tabSummary.textContent = items.length ? `${items.length} tab${items.length === 1 ? "" : "s"}` : "No tabs loaded";
  elements.tabList.innerHTML = "";
  if (!items.length) {
    elements.tabList.append(emptyElement("Tabs appear after a session starts."));
    return;
  }
  items.forEach((tab) => {
    const item = document.createElement("div");
    item.className = "tab-row";
    item.role = "listitem";
    item.innerHTML = `
      <span class="${tab.active ? "tab-dot active" : "tab-dot"}" aria-hidden="true"></span>
      <span>${escapeHtml(tab.url || "about:blank")}</span>
    `;
    elements.tabList.append(item);
  });
}

function renderPolicy(policy) {
  state.lastPolicy = policy;
  const allowed = Boolean(policy?.allowed);
  elements.policyStatus.textContent = policy?.reason || (allowed ? "allowed" : "not checked");
  elements.policyStatus.dataset.state = allowed ? "allowed" : "denied";
  elements.policyDetails.innerHTML = "";
  if (!policy) {
    elements.policyDetails.append(emptyElement("Run Check or Navigate to evaluate the URL."));
    return;
  }
  const details = [
    ["Decision", allowed ? "Allowed" : "Denied"],
    ["Reason", policy.reason || "unknown"],
    ["URL", policy.redacted_url || policy.url || ""],
    ["Normalized", policy.normalized_url || ""],
    ["Blocked address", policy.blocked_address || ""],
  ].filter(([, value]) => value);
  details.forEach(([term, value]) => {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = term;
    dd.textContent = String(value);
    elements.policyDetails.append(dt, dd);
  });
}

function renderSnapshot(payload) {
  const snapshot = payload.snapshot || "";
  elements.snapshotOutput.textContent = snapshot || "Snapshot returned no accessibility content.";
  elements.snapshotMeta.textContent = payload.url ? `Captured from ${payload.url}` : "Snapshot captured.";
  renderRefs(snapshot);
}

function renderRefs(snapshot) {
  const refs = extractRefs(snapshot);
  elements.refsSummary.textContent = `${refs.length} ref${refs.length === 1 ? "" : "s"}`;
  elements.refsList.innerHTML = "";
  if (!refs.length) {
    elements.refsList.append(emptyElement("No refs found in this snapshot."));
    return;
  }
  refs.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ref-row";
    button.innerHTML = `
      <span>${escapeHtml(item.ref)}</span>
      <small>${escapeHtml(item.label)}</small>
    `;
    button.addEventListener("click", () => {
      elements.refInput.value = item.ref;
    });
    elements.refsList.append(button);
  });
}

function extractRefs(snapshot) {
  const seen = new Set();
  return String(snapshot || "")
    .split("\n")
    .flatMap((line) => {
      const matches = [...line.matchAll(/\[(?:ref=)?([A-Za-z0-9_.:-]+)\]/g)];
      return matches.map((match) => ({ ref: match[1], label: line.trim().slice(0, 140) }));
    })
    .filter((item) => {
      if (seen.has(item.ref)) {
        return false;
      }
      seen.add(item.ref);
      return true;
    });
}

function renderScreenshot(payload) {
  elements.screenshotFrame.innerHTML = "";
  if (payload.data && payload.mime_type) {
    const image = document.createElement("img");
    image.alt = "Browser screenshot";
    image.src = `data:${payload.mime_type};base64,${payload.data}`;
    elements.screenshotFrame.append(image);
    elements.screenshotMeta.textContent = payload.url ? `Captured from ${payload.url}` : "Screenshot captured.";
    return;
  }
  const caption = document.createElement("figcaption");
  caption.textContent = "Screenshot returned no image data.";
  elements.screenshotFrame.append(caption);
}

function renderLogs(container, meta, items, emptyText) {
  const logs = Array.isArray(items) ? items : [];
  meta.textContent = logs.length ? `${logs.length} record${logs.length === 1 ? "" : "s"} loaded.` : emptyText;
  container.innerHTML = "";
  if (!logs.length) {
    container.append(emptyElement(emptyText));
    return;
  }
  logs.forEach((item) => {
    const row = document.createElement("article");
    row.className = "log-row";
    row.textContent = JSON.stringify(item, null, 2);
    container.append(row);
  });
}

function renderAudit(items) {
  const audit = Array.isArray(items) ? items : [];
  elements.auditMeta.textContent = audit.length ? `${audit.length} audited action${audit.length === 1 ? "" : "s"}.` : "No visible audit records.";
  elements.auditList.innerHTML = "";
  if (!audit.length) {
    elements.auditList.append(emptyElement("No visible audit records."));
    return;
  }
  audit.slice().reverse().forEach((item) => {
    const row = document.createElement("article");
    row.className = "audit-row";
    row.innerHTML = `
      <strong>${escapeHtml(item.action || "action")}</strong>
      <span data-state="${escapeHtml(item.status || "unknown")}">${escapeHtml(item.status || "unknown")}</span>
      <small>${escapeHtml(item.reason || item.url || item.session_id || "")}</small>
    `;
    elements.auditList.append(row);
  });
}

function markRefreshFailure(label, error) {
  const detail = errorDetail(error);
  if (label === "tabs") {
    elements.tabSummary.textContent = "Tabs refresh failed.";
    elements.tabList.innerHTML = "";
    elements.tabList.append(emptyElement(detail));
    return;
  }
  if (label === "snapshot") {
    elements.snapshotMeta.textContent = "Snapshot refresh failed.";
    elements.snapshotOutput.textContent = detail;
    renderRefs("");
    return;
  }
  if (label === "console") {
    renderLogs(elements.consoleList, elements.consoleMeta, [], `Console refresh failed: ${detail}`);
    return;
  }
  if (label === "network") {
    renderLogs(elements.networkList, elements.networkMeta, [], `Network refresh failed: ${detail}`);
  }
}

function errorDetail(error) {
  const payload = error?.payload;
  return payload?.detail || payload?.error || error?.message || "Browser refresh failed.";
}

async function refreshStatus() {
  const status = await callBackend({ action: "status" });
  renderStatus(status);
  return status;
}

async function preflightUrl(url = elements.urlInput.value.trim(), mode = activeMode()) {
  const policy = (await callBackend({ action: "policy.preflight", url, mode })).policy;
  renderPolicy(policy);
  return policy;
}

async function ensureSession(mode = elements.modeInput.value) {
  if (state.activeSessionId) {
    return state.activeSessionId;
  }
  const created = await callBackend({ action: "session.create", mode });
  state.activeSessionId = created.session_id;
  await refreshStatus();
  return state.activeSessionId;
}

async function createSession() {
  await withBusy(async () => {
    clearMessage();
    const mode = elements.modeInput.value;
    const created = await callBackend({ action: "session.create", mode });
    state.activeSessionId = created.session_id;
    await refreshStatus();
    setMessage(`Created ${created.mode || mode} session ${shortId(created.session_id)}.`, "success");
  });
}

async function closeSession() {
  const sessionId = state.activeSessionId;
  if (!sessionId) {
    setMessage("Select a session to close.", "warning");
    return;
  }
  await withBusy(async () => {
    await callBackend({ action: "session.close", session_id: sessionId });
    state.activeSessionId = "";
    await refreshStatus();
    setMessage(`Closed session ${shortId(sessionId)}.`, "success");
  });
}

async function navigate(event) {
  event?.preventDefault();
  await withBusy(async () => {
    clearMessage();
    const targetUrl = elements.urlInput.value.trim();
    const mode = activeMode();
    const policy = await preflightUrl(targetUrl, mode);
    if (!policy.allowed) {
      setPane("snapshot-pane");
      setMessage(`Policy denied navigation: ${policy.reason || "unknown"}.`, "error");
      return;
    }
    const sessionId = await ensureSession(mode);
    const body = { action: "navigate", session_id: sessionId, url: targetUrl };
    if (mode === DEV_MODE) {
      body.mode = DEV_MODE;
    }
    const result = await callBackend(body);
    await refreshStatus();
    const refreshFailures = await refreshInspectionPanes();
    setPane("snapshot-pane");
    setActionOutcome(`Navigated to ${result.url || targetUrl}`, refreshFailures);
  });
}

async function refreshInspectionPanes() {
  const tasks = [
    { label: "tabs", run: loadTabs },
    { label: "snapshot", run: captureSnapshot },
    { label: "console", run: loadConsole },
    { label: "network", run: loadNetwork },
  ];
  const failures = [];
  await Promise.all(
    tasks.map(async (task) => {
      try {
        await task.run();
      } catch (error) {
        markRefreshFailure(task.label, error);
        failures.push(`${task.label}: ${errorDetail(error)}`);
      }
    }),
  );
  return failures;
}

function setActionOutcome(message, refreshFailures) {
  if (refreshFailures.length) {
    setMessage(`${message}, but ${refreshFailures.join("; ")}`, "warning");
    return;
  }
  setMessage(`${message}.`, "success");
}

async function captureSnapshot() {
  const sessionId = requireSessionId();
  const payload = await callBackend({ action: "snapshot", session_id: sessionId });
  renderSnapshot(payload);
  setPane("snapshot-pane");
  return payload;
}

async function captureScreenshot() {
  const sessionId = requireSessionId();
  const payload = await callBackend({
    action: "screenshot",
    session_id: sessionId,
    full_page: elements.fullPageInput.checked,
  });
  renderScreenshot(payload);
  setPane("screenshot-pane");
  return payload;
}

async function loadTabs() {
  const sessionId = requireSessionId();
  const payload = await callBackend({ action: "tabs", session_id: sessionId });
  const sessionTabs = tabsFromPayload(payload, sessionId);
  renderTabs(sessionTabs);
  await refreshStatus();
  return payload;
}

async function loadConsole() {
  const sessionId = requireSessionId();
  const payload = await callBackend({ action: "console.messages", session_id: sessionId, limit: 100 });
  renderLogs(elements.consoleList, elements.consoleMeta, payload.messages, "No console messages loaded.");
  setPane("console-pane");
  return payload;
}

async function loadNetwork() {
  const sessionId = requireSessionId();
  const payload = await callBackend({ action: "network.requests", session_id: sessionId, limit: 100 });
  renderLogs(elements.networkList, elements.networkMeta, payload.requests, "No network requests loaded.");
  setPane("network-pane");
  return payload;
}

async function waitForPage() {
  const sessionId = requireSessionId();
  const payload = await callBackend({
    action: "wait_for",
    session_id: sessionId,
    state: elements.waitState.value,
    timeout_ms: 10000,
  });
  await refreshStatus();
  setMessage(`Waited for ${elements.waitState.value} on ${payload.url || "active tab"}.`, "success");
  return payload;
}

async function loadAudit() {
  const payload = await callBackend({ action: "audit.list" });
  renderAudit(payload.audit);
  setPane("audit-pane");
  return payload;
}

async function devInspectorAction(kind) {
  const sessionId = requireSessionId();
  const ref = elements.refInput.value.trim();
  if (!ref && kind !== "press_key") {
    throw new Error("Select or enter a snapshot ref first.");
  }
  const body = {
    action: kind,
    session_id: sessionId,
    mode: DEV_MODE,
    target_url: currentTargetUrl(),
  };
  if (kind === "click") {
    body.ref = ref;
  } else if (kind === "type") {
    body.ref = ref;
    body.text = elements.typeInput.value;
  } else {
    body.key = "Enter";
  }
  const payload = await callBackend(body);
  await refreshStatus();
  const refreshFailures = await refreshInspectionPanes();
  setActionOutcome(`${kind === "press_key" ? "Pressed Enter" : kind} completed`, refreshFailures);
  return payload;
}

function tabsFromPayload(payload, sessionId) {
  if (Array.isArray(payload.tabs)) {
    return payload.tabs;
  }
  if (Array.isArray(payload.sessions)) {
    const session = payload.sessions.find((item) => item.session_id === sessionId);
    return Array.isArray(session?.tabs) ? session.tabs : [];
  }
  return activeSession()?.tabs || [];
}

function requireSessionId() {
  if (!state.activeSessionId) {
    throw new Error("Create or select a Browser session first.");
  }
  return state.activeSessionId;
}

async function withBusy(action) {
  if (state.busy) {
    return;
  }
  setBusy(true);
  try {
    await action();
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

function handleError(error) {
  const payload = error?.payload;
  if (payload?.policy) {
    renderPolicy(payload.policy);
  }
  const detail = payload?.detail || error?.message || "Browser action failed.";
  const label = payload?.error ? `${payload.error}: ${detail}` : detail;
  setMessage(label, "error");
}

function updateControls() {
  const hasSession = Boolean(state.activeSessionId);
  const devMode = activeMode() === DEV_MODE;
  elements.app.dataset.mode = activeMode();
  elements.closeSessionButton.disabled = state.busy || !hasSession;
  elements.refreshTabsButton.disabled = state.busy || !hasSession;
  elements.snapshotButton.disabled = state.busy || !hasSession;
  elements.screenshotButton.disabled = state.busy || !hasSession;
  elements.consoleButton.disabled = state.busy || !hasSession;
  elements.networkButton.disabled = state.busy || !hasSession;
  elements.waitButton.disabled = state.busy || !hasSession;
  elements.clickButton.disabled = state.busy || !hasSession || !devMode;
  elements.typeButton.disabled = state.busy || !hasSession || !devMode;
  elements.pressKeyButton.disabled = state.busy || !hasSession || !devMode;
}

function optionElement(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function emptyElement(text) {
  const element = document.createElement("div");
  element.className = "empty-state";
  element.textContent = text;
  return element;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function notifyAppReady() {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: "maverick.app.ready", app_id: "browser" }, window.location.origin);
  }
}

document.querySelectorAll(".pane-tabs button").forEach((button) => {
  button.addEventListener("click", () => setPane(button.dataset.pane));
});

elements.urlForm.addEventListener("submit", navigate);
elements.preflightButton.addEventListener("click", () => withBusy(preflightUrl));
elements.newSessionButton.addEventListener("click", createSession);
elements.closeSessionButton.addEventListener("click", closeSession);
elements.sessionPicker.addEventListener("change", () => {
  state.activeSessionId = elements.sessionPicker.value;
  renderSessions();
  renderTabs(activeSession()?.tabs || []);
  updateControls();
});
elements.modeInput.addEventListener("change", updateControls);
elements.refreshTabsButton.addEventListener("click", () => withBusy(loadTabs));
elements.snapshotButton.addEventListener("click", () => withBusy(captureSnapshot));
elements.screenshotButton.addEventListener("click", () => withBusy(captureScreenshot));
elements.consoleButton.addEventListener("click", () => withBusy(loadConsole));
elements.networkButton.addEventListener("click", () => withBusy(loadNetwork));
elements.waitButton.addEventListener("click", () => withBusy(waitForPage));
elements.auditButton.addEventListener("click", () => withBusy(loadAudit));
elements.clickButton.addEventListener("click", () => withBusy(() => devInspectorAction("click")));
elements.typeButton.addEventListener("click", () => withBusy(() => devInspectorAction("type")));
elements.pressKeyButton.addEventListener("click", () => withBusy(() => devInspectorAction("press_key")));

renderPolicy(null);
renderRefs("");
renderAudit([]);
notifyAppReady();
refreshStatus().catch(handleError);
