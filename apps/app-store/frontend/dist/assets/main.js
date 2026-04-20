const state = {
  apps: [],
  installations: [],
  localApps: [],
  pinnedApps: [],
  workspaces: [],
  selectedWorkspaces: new Set(),
  pending: new Set(),
  activeTab: "catalog",
};

const catalogGrid = document.querySelector("#catalogGrid");
const installedList = document.querySelector("#installedList");
const localList = document.querySelector("#localList");
const workspaceList = document.querySelector("#workspaceList");
const statusText = document.querySelector("#statusText");
const refreshButton = document.querySelector("#refreshButton");
const tabButtons = [...document.querySelectorAll("[data-tab]")];
const panels = [...document.querySelectorAll("[data-panel]")];

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error || `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

function setStatus(text, kind = "idle") {
  statusText.textContent = text;
  statusText.dataset.kind = kind;
}

function latestVersion(app) {
  return (app.versions || []).find((version) => version.version === app.latest_version) || (app.versions || [])[0] || null;
}

function selectedWorkspaceIds() {
  return [...state.selectedWorkspaces];
}

function selectedInstallations(appId) {
  const selected = new Set(selectedWorkspaceIds());
  return state.installations.filter((item) => item.app_id === appId && selected.has(item.workspace_id));
}

function installationFor(appId, workspaceId) {
  return state.installations.find((item) => item.app_id === appId && item.workspace_id === workspaceId) || null;
}

function isAppPending(appId) {
  return [...state.pending].some((key) => key.startsWith(`${appId}:`));
}

function selectedInstallState(appId) {
  const workspaceIds = selectedWorkspaceIds();
  const installedCount = selectedInstallations(appId).length;
  return {
    workspaceCount: workspaceIds.length,
    installedCount,
    isInstalledEverywhere: workspaceIds.length > 0 && installedCount === workspaceIds.length,
    isPartiallyInstalled: installedCount > 0 && installedCount < workspaceIds.length,
  };
}

function isPinned(appId) {
  return state.pinnedApps.includes(appId);
}

function appById(appId) {
  return state.apps.find((app) => app.app_id === appId) || null;
}

function titleizeAppId(appId) {
  return appId.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function appSummary(appId) {
  const app = appById(appId);
  const installation = state.installations.find((item) => item.app_id === appId);
  return {
    app_id: appId,
    description: app?.description || "Installed workspace app.",
    latest_version: app?.latest_version || installation?.active_version || "",
    name: app?.name || titleizeAppId(appId),
    publisher: app?.publisher || "",
    surfaces: app?.surfaces || [],
    versions: app?.versions || [],
  };
}

function localAppSummary(item) {
  return {
    app_id: item.app_id,
    description: item.description || "Workspace-local app project.",
    latest_version: item.version || item.active_version || "",
    name: item.name || titleizeAppId(item.app_id),
    publisher: item.publisher || "workspace",
    surfaces: [],
    versions: [{ version: item.version || item.active_version || "" }],
    localStatus: item.status || "uninstalled",
    workspace_id: item.workspace_id,
    project_root: item.project_root,
  };
}

function surfaceLabel(app) {
  const surfaces = app.surfaces || [];
  if (surfaces.length === 0) return "No declared surfaces";
  return surfaces.join(" / ");
}

function statusLabel(appId) {
  const installState = selectedInstallState(appId);
  if (installState.workspaceCount === 0) return "Select a workspace";
  if (installState.isInstalledEverywhere) {
    return `Installed in ${installState.installedCount}/${installState.workspaceCount}`;
  }
  if (installState.isPartiallyInstalled) {
    return `Installed in ${installState.installedCount}/${installState.workspaceCount}`;
  }
  return "Not installed";
}

function openApp(appId, workspaceId = null) {
  const message = { type: "maverick.app.open-app", app_id: appId };
  if (workspaceId) {
    message.workspace_id = workspaceId;
    message.params = { workspace_id: workspaceId };
  }
  window.parent?.postMessage(message, window.location.origin);
}

function notifyPinnedAppsChanged() {
  window.parent?.postMessage(
    {
      type: "maverick.app.data-changed",
      owner_app_id: "app-store",
      resource: "pinned-apps",
    },
    window.location.origin,
  );
}

function renderWorkspaces() {
  workspaceList.replaceChildren();
  state.workspaces.forEach((workspace) => {
    const label = document.createElement("label");
    label.className = "workspace-chip";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedWorkspaces.has(workspace.workspace_id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.selectedWorkspaces.add(workspace.workspace_id);
      } else {
        state.selectedWorkspaces.delete(workspace.workspace_id);
      }
      render();
    });
    const text = document.createElement("span");
    text.textContent = workspace.name || workspace.workspace_id;
    label.append(checkbox, text);
    workspaceList.append(label);
  });
}

function renderAppIcon(app) {
  const icon = document.createElement("span");
  icon.className = "app-row-icon";
  icon.textContent = (app.name || app.app_id).slice(0, 1).toUpperCase();
  return icon;
}

function closeOpenMenus() {
  document.querySelectorAll(".app-row-menu[open]").forEach((menu) => {
    menu.removeAttribute("open");
  });
}

function renderMenuItem({ label, icon, disabled = false, danger = false, action }) {
  const button = document.createElement("button");
  button.className = "app-row-menu-item";
  button.type = "button";
  button.disabled = disabled;
  if (danger) {
    button.dataset.intent = "danger";
  }
  const iconEl = document.createElement("span");
  iconEl.className = "material-symbols-rounded";
  iconEl.setAttribute("aria-hidden", "true");
  iconEl.textContent = icon;
  const text = document.createElement("span");
  text.textContent = label;
  button.append(iconEl, text);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    closeOpenMenus();
    if (!disabled) {
      action();
    }
  });
  return button;
}

function renderWorkspaceAssignmentsMenu(app, version, mode) {
  const assignments = document.createElement("div");
  assignments.className = "app-row-menu-section";
  const title = document.createElement("p");
  title.className = "app-row-menu-label";
  title.textContent = "Workspaces";
  assignments.append(title);
  state.workspaces.forEach((workspace) => {
    const workspaceId = workspace.workspace_id;
    const assignmentKey = `${app.app_id}:${version?.version || app.latest_version || ""}:${workspaceId}`;
    const label = document.createElement("label");
    label.className = "app-row-menu-check";
    label.title = `Toggle ${app.name} in ${workspace.name || workspaceId}`;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(installationFor(app.app_id, workspaceId));
    checkbox.disabled = mode === "local" || !version?.version || state.pending.has(assignmentKey);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", (event) => {
      event.stopPropagation();
      setWorkspaceAssignment(app, version, workspaceId, checkbox.checked);
    });
    const text = document.createElement("span");
    text.textContent = workspace.name || workspaceId;
    label.append(checkbox, text);
    assignments.append(label);
  });
  return assignments;
}

function renderMoreOptions(app, mode, version, installState) {
  const menu = document.createElement("details");
  menu.className = "app-row-menu";
  menu.addEventListener("click", (event) => event.stopPropagation());
  menu.addEventListener("toggle", () => {
    if (!menu.open) {
      return;
    }
    document.querySelectorAll(".app-row-menu[open]").forEach((otherMenu) => {
      if (otherMenu !== menu) {
        otherMenu.removeAttribute("open");
      }
    });
  });
  const summary = document.createElement("summary");
  summary.className = "app-row-more";
  summary.setAttribute("aria-label", `More options for ${app.name || app.app_id}`);
  summary.title = "More options";
  const icon = document.createElement("span");
  icon.className = "material-symbols-rounded";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "more_horiz";
  summary.append(icon);
  const panel = document.createElement("div");
  panel.className = "app-row-menu-panel";
  const installed = installState.installedCount > 0;
  const isPending = isAppPending(app.app_id);
  panel.append(
    renderMenuItem({
      label: isPinned(app.app_id) ? "Unpin shortcut" : "Pin shortcut",
      icon: "push_pin",
      disabled: !installed || isPending,
      action: () => togglePinnedApp(app),
    }),
  );
  if (mode === "local") {
    panel.append(
      renderMenuItem({
        label: installed ? "Uninstall from workspace" : "Install in workspace",
        icon: installed ? "delete" : "download",
        danger: installed,
        disabled: !app.workspace_id || isPending,
        action: () => (installed ? uninstallLocalApp(app) : installLocalApp(app)),
      }),
    );
    panel.append(
      renderMenuItem({
        label: "Delete app completely",
        icon: "delete_forever",
        danger: true,
        disabled: !app.workspace_id || isPending,
        action: () => deleteLocalApp(app),
      }),
    );
  } else {
    panel.append(
      renderMenuItem({
        label: installState.isInstalledEverywhere ? "Uninstall from selected" : "Install in selected",
        icon: installState.isInstalledEverywhere ? "delete" : "download",
        danger: installState.isInstalledEverywhere,
        disabled: !version?.version || installState.workspaceCount === 0 || isPending,
        action: () => (installState.isInstalledEverywhere ? uninstallApp(app, version) : installApp(app, version)),
      }),
    );
    panel.append(renderWorkspaceAssignmentsMenu(app, version, mode));
  }
  menu.append(summary, panel);
  return menu;
}

function renderRow(app, mode) {
  const version = latestVersion(app) || { version: app.latest_version || "" };
  const installState = selectedInstallState(app.app_id);
  const row = document.createElement("article");
  row.className = "app-row";
  row.dataset.mode = mode;
  row.title = installState.installedCount > 0 ? `Open ${app.name}` : `${app.name} is not installed`;
  row.addEventListener("click", () => {
    if (installState.installedCount > 0) {
      openApp(app.app_id, mode === "local" ? app.workspace_id : null);
    }
  });

  const copy = document.createElement("div");
  copy.className = "app-row-copy";
  const title = document.createElement("h3");
  title.textContent = app.name || app.app_id;
  const description = document.createElement("p");
  description.textContent = app.description || "";
  copy.append(title, description);

  const meta = document.createElement("div");
  meta.className = "app-row-meta";
  const versionBadge = document.createElement("span");
  versionBadge.className = "app-row-badge";
  versionBadge.textContent = version.version || "unknown";
  const status = document.createElement("span");
  status.className = "app-row-status";
  status.dataset.state = installState.isInstalledEverywhere ? "installed" : installState.isPartiallyInstalled ? "partial" : "available";
  status.textContent = statusLabel(app.app_id);
  meta.append(versionBadge, status);

  const details = document.createElement("div");
  details.className = "app-row-details";
  details.append(meta);
  if (mode === "local") {
    const localMeta = document.createElement("span");
    localMeta.className = "app-row-surfaces";
    localMeta.textContent = `${app.workspace_id || "workspace"} · ${app.localStatus || "uninstalled"}`;
    details.append(localMeta);
  }
  if (mode === "store") {
    const surfaces = document.createElement("span");
    surfaces.className = "app-row-surfaces";
    surfaces.textContent = surfaceLabel(app);
    details.append(surfaces);
  }

  const actionWrap = document.createElement("div");
  actionWrap.className = "app-row-actions";
  actionWrap.append(renderMoreOptions(app, mode, version, installState));
  const chevron = document.createElement("button");
  chevron.className = "app-row-chevron";
  chevron.type = "button";
  chevron.disabled = installState.installedCount === 0;
  chevron.setAttribute("aria-label", `Open ${app.name}`);
  const chevronIcon = document.createElement("span");
  chevronIcon.className = "material-symbols-rounded";
  chevronIcon.setAttribute("aria-hidden", "true");
  chevronIcon.textContent = "chevron_right";
  chevron.append(chevronIcon);
  chevron.addEventListener("click", (event) => {
    event.stopPropagation();
    if (installState.installedCount > 0) {
      openApp(app.app_id, mode === "local" ? app.workspace_id : null);
    }
  });
  actionWrap.append(chevron);

  row.append(renderAppIcon(app), copy, details, actionWrap);
  return row;
}

function renderInstalled() {
  installedList.replaceChildren();
  const selected = new Set(selectedWorkspaceIds());
  const appIds = [...new Set(state.installations.filter((item) => selected.has(item.workspace_id)).map((item) => item.app_id))].sort();
  if (appIds.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No apps installed in selected workspaces.";
    installedList.append(empty);
    return;
  }
  appIds.forEach((appId) => {
    installedList.append(renderRow(appSummary(appId), "installed"));
  });
}

function renderStore() {
  catalogGrid.replaceChildren();
  if (!state.apps.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No apps are available in the configured catalog.";
    catalogGrid.append(empty);
    return;
  }
  state.apps.forEach((app) => catalogGrid.append(renderRow(app, "store")));
}

function renderLocal() {
  localList.replaceChildren();
  const selected = new Set(selectedWorkspaceIds());
  const rows = state.localApps.filter((item) => selected.has(item.workspace_id));
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No workspace-local app projects exist in the selected workspaces.";
    localList.append(empty);
    return;
  }
  rows.forEach((item) => {
    const row = renderRow(localAppSummary(item), "local");
    row.dataset.localStatus = item.status || "uninstalled";
    localList.append(row);
  });
}

function renderTabs() {
  tabButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === state.activeTab);
  });
  panels.forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.panel === state.activeTab);
  });
}

function render() {
  renderTabs();
  renderInstalled();
  renderStore();
  renderLocal();
}

async function installApp(app, version) {
  const workspaceIds = selectedWorkspaceIds();
  const installKey = `${app.app_id}:${version.version}`;
  state.pending.add(installKey);
  render();
  setStatus(`Installing ${app.name}`, "busy");
  try {
    await requestJson("/api/app-store/install", {
      method: "POST",
      body: JSON.stringify({ app_id: app.app_id, version: version.version, workspace_ids: workspaceIds }),
    });
    await requestJson("/api/apps/app-store/backend", {
      method: "POST",
      body: JSON.stringify({ action: "remember_install", app_id: app.app_id, version: version.version, workspace_ids: workspaceIds }),
    }).catch(() => null);
    await refreshInstallations();
    setStatus(`Installed ${app.name}`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(installKey);
    render();
  }
}

async function uninstallApp(app, version) {
  const workspaceIds = selectedWorkspaceIds();
  const installKey = `${app.app_id}:${version.version}`;
  state.pending.add(installKey);
  render();
  setStatus(`Uninstalling ${app.name}`, "busy");
  try {
    await requestJson("/api/app-store/uninstall", {
      method: "POST",
      body: JSON.stringify({ app_id: app.app_id, workspace_ids: workspaceIds }),
    });
    await refreshInstallations();
    setStatus(`Uninstalled ${app.name}`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(installKey);
    render();
  }
}

async function installLocalApp(app) {
  const workspaceId = app.workspace_id;
  const pendingKey = `${app.app_id}:local:${workspaceId || ""}`;
  if (!workspaceId) {
    setStatus("Workspace-local app is missing its owner workspace", "error");
    return;
  }
  state.pending.add(pendingKey);
  render();
  setStatus(`Installing ${app.name}`, "busy");
  try {
    await requestJson("/api/app-store/install-local", {
      method: "POST",
      body: JSON.stringify({ app_id: app.app_id, workspace_ids: [workspaceId] }),
    });
    await refreshInstallations();
    setStatus(`Installed ${app.name}`, "ok");
    openApp(app.app_id, workspaceId);
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(pendingKey);
    render();
  }
}

async function uninstallLocalApp(app) {
  const workspaceId = app.workspace_id;
  const pendingKey = `${app.app_id}:local:${workspaceId || ""}`;
  if (!workspaceId) {
    setStatus("Workspace-local app is missing its owner workspace", "error");
    return;
  }
  state.pending.add(pendingKey);
  render();
  setStatus(`Uninstalling ${app.name}`, "busy");
  try {
    await requestJson("/api/app-store/uninstall", {
      method: "POST",
      body: JSON.stringify({ app_id: app.app_id, workspace_ids: [workspaceId] }),
    });
    await refreshInstallations();
    setStatus(`Uninstalled ${app.name}`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(pendingKey);
    render();
  }
}

async function deleteLocalApp(app) {
  const workspaceId = app.workspace_id;
  const pendingKey = `${app.app_id}:delete:${workspaceId || ""}`;
  if (!workspaceId) {
    setStatus("Workspace-local app is missing its owner workspace", "error");
    return;
  }
  const confirmed = window.confirm(`Delete ${app.name} completely from ${workspaceId}? This removes the app source, installation, and workspace data.`);
  if (!confirmed) {
    return;
  }
  state.pending.add(pendingKey);
  render();
  setStatus(`Deleting ${app.name}`, "busy");
  try {
    await requestJson("/api/app-store/delete-local", {
      method: "POST",
      body: JSON.stringify({ app_id: app.app_id, workspace_ids: [workspaceId] }),
    });
    if (isPinned(app.app_id)) {
      const nextPinnedApps = state.pinnedApps.filter((pinnedAppId) => pinnedAppId !== app.app_id);
      const payload = await requestJson("/api/apps/app-store/backend", {
        method: "POST",
        body: JSON.stringify({ action: "pinned_apps.set", app_ids: nextPinnedApps }),
      }).catch(() => null);
      state.pinnedApps = payload?.state?.pinned_apps || nextPinnedApps;
      notifyPinnedAppsChanged();
    }
    await refreshInstallations();
    setStatus(`Deleted ${app.name}`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(pendingKey);
    render();
  }
}

async function setWorkspaceAssignment(app, version, workspaceId, shouldInstall) {
  const assignmentKey = `${app.app_id}:${version.version}:${workspaceId}`;
  state.pending.add(assignmentKey);
  render();
  setStatus(`${shouldInstall ? "Assigning" : "Removing"} ${app.name}`, "busy");
  try {
    await requestJson(shouldInstall ? "/api/app-store/install" : "/api/app-store/uninstall", {
      method: "POST",
      body: JSON.stringify({ app_id: app.app_id, version: version.version, workspace_ids: [workspaceId] }),
    });
    await refreshInstallations();
    setStatus(`${shouldInstall ? "Assigned" : "Removed"} ${app.name}`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(assignmentKey);
    render();
  }
}

async function refreshInstallations() {
  const payload = await requestJson("/api/app-store/installations");
  state.installations = payload.items || [];
  state.localApps = payload.local_apps || [];
}

async function refreshPinnedApps() {
  const payload = await requestJson("/api/apps/app-store/backend", {
    method: "POST",
    body: JSON.stringify({ action: "pinned_apps.list" }),
  });
  state.pinnedApps = payload.pinned_apps || [];
}

async function togglePinnedApp(app) {
  const pendingKey = `${app.app_id}:pin`;
  state.pending.add(pendingKey);
  render();
  setStatus(`${isPinned(app.app_id) ? "Removing" : "Pinning"} ${app.name}`, "busy");
  try {
    const payload = await requestJson("/api/apps/app-store/backend", {
      method: "POST",
      body: JSON.stringify({ action: "pinned_apps.toggle", app_id: app.app_id }),
    });
    state.pinnedApps = payload.state?.pinned_apps || [];
    notifyPinnedAppsChanged();
    setStatus(`${app.name} shortcut updated`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(pendingKey);
    render();
  }
}

async function load() {
  setStatus("Loading", "busy");
  const [workspaces, catalog, installations, pinned] = await Promise.all([
    requestJson("/api/workspaces"),
    requestJson("/api/app-store/apps"),
    requestJson("/api/app-store/installations"),
    requestJson("/api/apps/app-store/backend", {
      method: "POST",
      body: JSON.stringify({ action: "pinned_apps.list" }),
    }),
  ]);
  state.workspaces = workspaces.items || [];
  state.apps = catalog.items || [];
  state.installations = installations.items || [];
  state.localApps = installations.local_apps || [];
  state.pinnedApps = pinned.pinned_apps || [];
  state.selectedWorkspaces = new Set([workspaces.active_workspace_id || state.workspaces[0]?.workspace_id].filter(Boolean));
  renderWorkspaces();
  render();
  setStatus(`${state.apps.length} apps`, "ok");
}

refreshButton.addEventListener("click", () => {
  load().catch((error) => {
    setStatus(error.message, "error");
  });
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.activeTab = button.dataset.tab || "catalog";
    render();
  });
});

document.addEventListener("click", () => closeOpenMenus());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeOpenMenus();
  }
});

load().catch((error) => {
  setStatus(error.message, "error");
});
