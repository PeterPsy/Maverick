import { loadCachedCatalog, requestJson } from "./appStoreApi.js";
import { isExactMaverickParentMessage } from "@maverick/pwa-cache";

const state = {
  apps: [],
  catalogApps: [],
  serverApps: [],
  installations: [],
  localApps: [],
  pinnedApps: [],
  workspaces: [],
  isLoading: true,
  catalogReady: false,
  authorityReady: false,
  selectedWorkspaces: new Set(),
  pending: new Set(),
  publicIdentities: {},
};

const FOLDER_SKELETONS = [
  { accent: "#00c6ff", gradient: "linear-gradient(135deg, rgba(0, 198, 255, 0.44), rgba(0, 114, 255, 0.24))" },
  { accent: "#d4d4d4", gradient: "linear-gradient(135deg, rgba(212, 212, 212, 0.38), rgba(115, 115, 115, 0.2))" },
  { accent: "#f5f5f5", gradient: "linear-gradient(135deg, rgba(255, 255, 255, 0.18), rgba(245, 245, 245, 0.34))" },
  { accent: "#f59e0b", gradient: "linear-gradient(135deg, rgba(245, 158, 11, 0.42), rgba(239, 68, 68, 0.24))" },
  { accent: "#e5e5e5", gradient: "linear-gradient(135deg, rgba(229, 229, 229, 0.34), rgba(82, 82, 82, 0.2))" },
  { accent: "#f80759", gradient: "linear-gradient(135deg, rgba(248, 7, 89, 0.42), rgba(188, 78, 156, 0.24))" },
  { accent: "#8e2de2", gradient: "linear-gradient(135deg, rgba(142, 45, 226, 0.42), rgba(74, 0, 224, 0.24))" },
];

const storeShell = document.querySelector(".store-shell");
const catalogGrid = document.querySelector("#catalogGrid");
const stalePinsSection = document.querySelector("#stalePinsSection");
const stalePinList = document.querySelector("#stalePinList");
const featuredAppsNode = document.querySelector("#featuredApps");
const searchNode = document.querySelector("#search");
const surfaceNode = document.querySelector("#surface");
const catalogStatsNode = document.querySelector("#catalogStats");
const serverList = document.querySelector("#serverList");
const installedList = document.querySelector("#installedList");
const localList = document.querySelector("#localList");
const publicSubmissionId = document.querySelector("#publicSubmissionId");
const publicSubmissionLookup = document.querySelector("#publicSubmissionLookup");
const publicSubmissionResult = document.querySelector("#publicSubmissionResult");
const workspaceList = document.querySelector("#workspaceList");
const navigationButtons = [...document.querySelectorAll("[data-target]")];
const promotionModal = document.querySelector("#promotionModal");
const promotionModalTitle = document.querySelector("#promotionModalTitle");
const promotionModalBody = document.querySelector("#promotionModalBody");
const promotionModalActions = document.querySelector("#promotionModalActions");
const promotionModalClose = document.querySelector("#promotionModalClose");

function applyCatalog(payload) {
  state.catalogApps = payload.items || [];
  state.apps = mergeCatalogAndServerApps(state.catalogApps, state.serverApps);
}

function setStatus() {}

function setBusy(node, busy) {
  if (!node) return;
  if (busy) {
    node.setAttribute("aria-busy", "true");
    return;
  }
  node.removeAttribute("aria-busy");
}

function syncLoadingChrome() {
  storeShell?.classList.toggle("is-loading", state.isLoading);
  [searchNode, surfaceNode, publicSubmissionId, publicSubmissionLookup].forEach((node) => {
    if (node) {
      node.disabled = state.isLoading;
    }
  });
}

function skeletonBlock(className, tagName = "span") {
  const node = document.createElement(tagName);
  node.className = className;
  node.setAttribute("aria-hidden", "true");
  return node;
}

function skeletonLine(size) {
  return skeletonBlock(`store-loading-skeleton__line store-loading-skeleton__line--${size}`);
}

function renderWorkspaceSkeleton() {
  if (!workspaceList) return;
  workspaceList.replaceChildren();
  setBusy(workspaceList, true);
  Array.from({ length: 3 }).forEach((_, index) => {
    const chip = skeletonBlock("workspace-chip workspace-chip--skeleton", "span");
    chip.append(skeletonLine(index === 0 ? "workspace-wide" : "workspace"));
    workspaceList.append(chip);
  });
}

function renderFeaturedSkeleton() {
  if (!featuredAppsNode) return;
  featuredAppsNode.replaceChildren();
  setBusy(featuredAppsNode, true);
  Array.from({ length: 3 }).forEach((_, index) => {
    const card = skeletonBlock(`feature-card feature-card--${index + 1} feature-card--skeleton`, "article");
    const copy = skeletonBlock("store-loading-skeleton__stack", "div");
    copy.append(skeletonLine("kicker"), skeletonLine(index === 0 ? "feature-title-wide" : "feature-title"), skeletonLine("feature-copy"));
    card.append(copy, skeletonBlock("store-loading-skeleton__button"), skeletonBlock("store-loading-skeleton__icon feature-icon"));
    featuredAppsNode.append(card);
  });
}

function renderStatsSkeleton() {
  if (!catalogStatsNode) return;
  catalogStatsNode.replaceChildren();
  catalogStatsNode.classList.add("store-stats--skeleton");
  catalogStatsNode.append(skeletonLine("stats"), skeletonLine("stats-short"), skeletonLine("stats"));
}

function renderFolderSkeletonCard(definition, index) {
  const card = skeletonBlock("app-folder-card app-folder-card--skeleton", "article");
  card.style.setProperty("--folder-gradient", definition.gradient);
  card.style.setProperty("--folder-accent", definition.accent);
  card.style.animationDelay = `${90 + index * 55}ms`;

  const glow = skeletonBlock("app-folder-glow", "div");

  const scene = skeletonBlock("app-folder-scene", "div");
  scene.append(
    skeletonBlock("app-folder-back", "div"),
    skeletonBlock("app-folder-tab", "div"),
    skeletonBlock("app-folder-front", "div"),
    skeletonBlock("app-folder-shine", "div"),
  );

  const copy = skeletonBlock("app-folder-copy app-folder-copy--skeleton", "div");
  copy.append(skeletonLine("folder-title"));

  const hint = skeletonBlock("app-folder-hint app-folder-hint--skeleton", "div");
  hint.append(skeletonLine("folder-hint"));

  card.append(glow, scene, copy, hint);
  return card;
}

function renderFolderGridSkeleton() {
  if (!catalogGrid) return;
  const grid = skeletonBlock("app-folder-grid app-folder-grid--skeleton", "div");
  FOLDER_SKELETONS.forEach((definition, index) => {
    grid.append(renderFolderSkeletonCard(definition, index));
  });
  catalogGrid.replaceChildren(grid);
  setBusy(catalogGrid, true);
}

function renderLoading() {
  if (stalePinsSection) {
    stalePinsSection.hidden = true;
  }
  stalePinList?.replaceChildren();
  renderFolderGridSkeleton();
}

function clearLoadingState() {
  [
    catalogGrid,
  ].forEach((node) => setBusy(node, false));
  catalogStatsNode?.classList.remove("store-stats--skeleton");
}

function latestVersion(app) {
  return (app.versions || []).find((version) => version.version === app.latest_version) || (app.versions || [])[0] || null;
}

function formatBytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(value) || 0;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function categoryLabel(app, installation = null) {
  const surfaces = normalizeSurfaces(app, installation);
  if (frontendRole(app, installation) === "workspace") return "Workspace frontend";
  if (frontendRole(app, installation) === "supporting") return "Supporting extension";
  if (surfaces.includes("mcp")) return "Agent-ready tools";
  if (surfaces.includes("cli")) return "Command utilities";
  if (surfaces.includes("backend")) return "Server extensions";
  return "Maverick apps";
}

function frontendPresentation(app = {}, installation = null) {
  if (window.MaverickFrontendPresentation?.frontendPresentation) {
    return window.MaverickFrontendPresentation.frontendPresentation(app, installation);
  }
  const source = installation ? { ...app, ...installation } : app;
  const role = String(source.frontend_role || source.presentation?.frontend_role || "").trim();
  const surfaces = Array.isArray(source.surfaces) ? source.surfaces.filter(Boolean) : [];
  const normalizedRole = ["workspace", "supporting", "none"].includes(role)
    ? role
    : surfaces.includes("supporting_frontend")
      ? "supporting"
      : surfaces.includes("frontend") || source.frontend_launchable === true
        ? "workspace"
        : "none";
  return {
    role: normalizedRole,
    launchable: normalizedRole === "workspace" && source.frontend_launchable !== false,
    surfaces,
    presentation: { frontend_role: normalizedRole },
  };
}

function normalizeSurfaces(app = {}, installation = null) {
  return frontendPresentation(app, installation).surfaces;
}

function frontendRole(app = {}, installation = null) {
  return frontendPresentation(app, installation).role;
}

function isFrontendLaunchable(app = {}, installation = null) {
  return frontendPresentation(app, installation).launchable;
}

function frontendAvailabilityLabel(app = {}, installation = null) {
  const role = frontendRole(app, installation);
  if (role === "workspace") {
    return "Workspace frontend";
  }
  if (role === "supporting") {
    return "Supporting frontend";
  }
  return "No frontend";
}

function canOpenInstalledApp(app, installState) {
  return installState.launchableCount > 0;
}

function filteredStoreApps() {
  const query = (searchNode?.value || "").trim().toLowerCase();
  const surface = surfaceNode?.value || "";
  return state.apps.filter((app) => {
    const surfaces = normalizeSurfaces(app);
    const text = `${app.app_id} ${app.name} ${app.description} ${app.publisher} ${frontendAvailabilityLabel(app)} ${surfaces.join(" ")}`.toLowerCase();
    const surfaceMatch = !surface || surfaces.includes(surface);
    return surfaceMatch && (!query || text.includes(query));
  });
}

function folderCatalogApps() {
  const entries = [];
  const seenKeys = new Set();
  const seenAppIds = new Set();
  const catalogIds = new Set(state.catalogApps.map((app) => app.app_id));
  const selected = new Set(selectedWorkspaceIds());

  const addEntry = (app, mode, key = `${mode}:${app.app_id}`) => {
    if (!app?.app_id || seenKeys.has(key)) {
      return;
    }
    seenKeys.add(key);
    seenAppIds.add(app.app_id);
    entries.push({ ...app, storeMode: mode });
  };

  state.catalogApps.forEach((app) => addEntry(app, "store"));
  state.serverApps.forEach((app) => {
    if (!catalogIds.has(app.app_id)) {
      addEntry(app, "server");
    }
  });
  state.localApps
    .filter((item) => selected.has(item.workspace_id))
    .forEach((item) => {
      const summary = localAppSummary(item);
      addEntry(summary, "local", `local:${summary.workspace_id || ""}:${summary.app_id}`);
    });

  [...new Set(state.installations.filter((item) => selected.has(item.workspace_id)).map((item) => item.app_id))]
    .sort()
    .forEach((appId) => {
      if (!seenAppIds.has(appId)) {
        addEntry(appSummary(appId), "installed");
      }
    });

  return entries;
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
  const installations = selectedInstallations(appId);
  const app = appById(appId);
  const launchableInstallations = installations.filter((installation) => isFrontendLaunchable(app || {}, installation));
  const presentationInstallation = launchableInstallations[0] || installations[0] || null;
  const installedCount = installations.length;
  return {
    workspaceCount: workspaceIds.length,
    installedCount,
    launchableCount: launchableInstallations.length,
    launchableWorkspaceId: launchableInstallations[0]?.workspace_id || null,
    presentationInstallation,
    isInstalledEverywhere: workspaceIds.length > 0 && installedCount === workspaceIds.length,
    isPartiallyInstalled: installedCount > 0 && installedCount < workspaceIds.length,
  };
}

function isPinned(appId) {
  return state.pinnedApps.includes(appId);
}

function canTogglePinnedApp(app, installState = selectedInstallState(app.app_id)) {
  if (isPinned(app.app_id)) {
    return true;
  }
  return installState.installedCount > 0 && installState.launchableCount > 0;
}

function appById(appId) {
  return state.apps.find((app) => app.app_id === appId) || null;
}

function mergeCatalogAndServerApps(catalogItems, serverItems) {
  const merged = [];
  const seen = new Set();
  [...catalogItems, ...serverItems].forEach((app) => {
    if (!app?.app_id || seen.has(app.app_id)) {
      return;
    }
    seen.add(app.app_id);
    merged.push(app);
  });
  return merged;
}

function titleizeAppId(appId) {
  return appId.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function appSummary(appId) {
  const app = appById(appId);
  const selected = new Set(selectedWorkspaceIds());
  const installation = state.installations.find((item) => item.app_id === appId && selected.has(item.workspace_id));
  const presentation = frontendPresentation(app || {}, installation);
  return {
    app_id: appId,
    description: app?.description || "Installed workspace app.",
    latest_version: app?.latest_version || installation?.active_version || "",
    name: app?.name || titleizeAppId(appId),
    publisher: app?.publisher || "",
    surfaces: presentation.surfaces,
    presentation: presentation.presentation,
    frontend_role: presentation.role,
    frontend_launchable: presentation.launchable,
    versions: app?.versions || [],
  };
}

function stalePinnedAppSummary(appId) {
  return {
    app_id: appId,
    description: "This pinned shortcut no longer matches any catalog, server, local, or installed app.",
    frontend_launchable: false,
    frontend_role: "none",
    latest_version: "",
    name: titleizeAppId(appId),
    presentation: { frontend_role: "none" },
    surfaces: [],
    versions: [],
  };
}

function localAppSummary(item) {
  const invalid = item.status === "invalid";
  const identityKey = `${item.workspace_id || ""}:${item.app_id}`;
  const publicIdentity = state.publicIdentities[identityKey] || {};
  const presentation = frontendPresentation(item);
  return {
    app_id: item.app_id,
    description: invalid && item.validation_error ? item.validation_error : item.description || "Workspace-local app project.",
    latest_version: item.version || item.active_version || "",
    name: item.name || titleizeAppId(item.app_id),
    publisher: item.publisher || "workspace",
    surfaces: presentation.surfaces,
    presentation: presentation.presentation,
    frontend_role: presentation.role,
    frontend_launchable: presentation.launchable,
    versions: [{ version: item.version || item.active_version || "" }],
    localStatus: item.status || "uninstalled",
    validation_error: item.validation_error || "",
    can_delete: item.can_delete !== false,
    can_promote: item.can_promote === true,
    promotion_kind: item.promotion_kind || "promote",
    promotion_detail: item.promotion_detail || "",
    public_app_uuid: publicIdentity.public_app_uuid || item.public_app_uuid || "",
    has_public_identity: Boolean(publicIdentity.public_app_uuid || item.public_app_uuid),
    workspace_id: item.workspace_id,
    project_root: item.project_root,
  };
}

function surfaceLabel(app, installation = null) {
  const surfaces = normalizeSurfaces(app, installation);
  const labels = [];
  if (frontendRole(app, installation) !== "none") {
    labels.push(frontendAvailabilityLabel(app, installation));
  }
  surfaces.forEach((surface) => {
    if (surface === "frontend" || surface === "supporting_frontend") {
      return;
    }
    labels.push({
      backend: "Backend",
      cli: "CLI",
      mcp: "MCP",
      skills: "Skills",
      widgets: "Widgets",
    }[surface] || surface);
  });
  if (labels.length === 0) return "No declared surfaces";
  return labels.join(" / ");
}

function sourceKindLabel(app) {
  if (app.source_kind === "external_bundle") return "External bundle";
  if (app.source_kind === "platform") return "Platform app";
  return "Server app";
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
  if (!state.authorityReady) return;
  const message = { type: "maverick.app.open-app", app_id: appId };
  if (workspaceId) {
    message.workspace_id = workspaceId;
    message.params = { workspace_id: workspaceId };
  }
  window.parent?.postMessage(message, "*");
}

function notifyPinnedAppsChanged() {
  window.parent?.postMessage(
    {
      type: "maverick.app.data-changed",
      owner_app_id: "app-store",
      resource: "pinned-apps",
    },
    "*",
  );
}

function renderWorkspaces() {
  if (!workspaceList) return;
  workspaceList.replaceChildren();
  setBusy(workspaceList, false);
  state.workspaces.forEach((workspace) => {
    const label = document.createElement("label");
    label.className = "workspace-chip";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedWorkspaces.has(workspace.workspace_id);
    checkbox.disabled = !state.authorityReady;
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

function renderAppIcon(app, installation = null) {
  if (window.MaverickAppIcons?.renderIcon) {
    return window.MaverickAppIcons.renderIcon(app, "app-row-icon", installation);
  }
  const frame = document.createElement("span");
  frame.className = "app-row-icon is-glyph";
  if (frontendRole(app, installation) === "supporting") {
    frame.classList.add("is-supporting-frontend");
  }
  if (!isFrontendLaunchable(app, installation)) {
    frame.classList.add("is-non-launchable");
  }
  frame.setAttribute("aria-hidden", "true");
  const glyph = document.createElement("span");
  glyph.className = "material-symbols-rounded";
  glyph.textContent = "deployed_code";
  frame.append(glyph);
  return frame;
}

function closeOpenMenus() {
  document.querySelectorAll(".app-row-menu[open]").forEach((menu) => {
    menu.removeAttribute("open");
  });
}

function closePromotionModal() {
  promotionModal.classList.add("is-hidden");
  promotionModal.setAttribute("aria-hidden", "true");
  promotionModalActions.replaceChildren();
}

function renderModalButton({ label, intent = "default", action }) {
  const button = document.createElement("button");
  button.className = "app-modal__button";
  button.type = "button";
  if (intent !== "default") {
    button.dataset.intent = intent;
  }
  button.textContent = label;
  button.addEventListener("click", action);
  return button;
}

function renderModalField(labelText, input) {
  const label = document.createElement("label");
  label.className = "app-modal__field";
  const text = document.createElement("span");
  text.textContent = labelText;
  label.append(text, input);
  return label;
}

function openPromotionModal({ title, body, actions }) {
  promotionModalTitle.textContent = title;
  promotionModalBody.textContent = body;
  promotionModalActions.replaceChildren(...actions);
  promotionModal.classList.remove("is-hidden");
  promotionModal.setAttribute("aria-hidden", "false");
}

function renderMenuItem({ label, icon, disabled = false, danger = false, action }) {
  const button = document.createElement("button");
  button.className = "app-row-menu-item";
  button.type = "button";
  button.disabled = disabled || !state.authorityReady;
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
    if (!button.disabled) {
      action();
    }
  });
  return button;
}

function workspaceAssignmentKey(app, version, mode, workspaceId) {
  const sourceKey = mode === "server" ? version?.source_id || version?.version : version?.version;
  return `${app.app_id}:${sourceKey || app.latest_version || ""}:${workspaceId}`;
}

function canAssignWorkspace(mode, version) {
  return mode === "server" ? Boolean(version?.source_id || version?.version) : Boolean(version?.version);
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
    const assignmentKey = workspaceAssignmentKey(app, version, mode, workspaceId);
    const label = document.createElement("label");
    label.className = "app-row-menu-check";
    label.title = `Toggle ${app.name} in ${workspace.name || workspaceId}`;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(installationFor(app.app_id, workspaceId));
    checkbox.disabled = !state.authorityReady || mode === "local" || !canAssignWorkspace(mode, version) || state.pending.has(assignmentKey);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", (event) => {
      event.stopPropagation();
      setWorkspaceAssignment(app, version, mode, workspaceId, checkbox.checked);
    });
    const text = document.createElement("span");
    text.textContent = workspace.name || workspaceId;
    label.append(checkbox, text);
    assignments.append(label);
  });
  return assignments;
}

function renderDetailSettingsSection(labelText) {
  const section = document.createElement("section");
  section.className = "app-detail-settings__section";
  const label = document.createElement("p");
  label.className = "app-detail-settings__label";
  label.textContent = labelText;
  section.append(label);
  return section;
}

function renderDetailSettingsGrid() {
  const grid = document.createElement("div");
  grid.className = "app-detail-settings__grid";
  return grid;
}

function renderDetailSettingsNote(text) {
  const note = document.createElement("p");
  note.className = "app-detail-settings__note";
  note.textContent = text;
  return note;
}

function renderDetailSettingButton({ label, icon, disabled = false, danger = false, action }) {
  const button = document.createElement("button");
  button.className = "app-detail-setting-button";
  button.type = "button";
  button.disabled = disabled || !state.authorityReady;
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
    if (!button.disabled) {
      action();
    }
  });
  return button;
}

function renderWorkspaceAssignmentsSettings(app, version, mode) {
  const section = renderDetailSettingsSection("Workspaces");
  const list = document.createElement("div");
  list.className = "app-detail-settings__check-list";
  if (!state.workspaces.length) {
    list.append(renderDetailSettingsNote("No workspaces available."));
    section.append(list);
    return section;
  }
  state.workspaces.forEach((workspace) => {
    const workspaceId = workspace.workspace_id;
    const assignmentKey = workspaceAssignmentKey(app, version, mode, workspaceId);
    const label = document.createElement("label");
    label.className = "app-detail-settings__check";
    label.title = `Toggle ${app.name} in ${workspace.name || workspaceId}`;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(installationFor(app.app_id, workspaceId));
    checkbox.disabled = !state.authorityReady || mode === "local" || !canAssignWorkspace(mode, version) || state.pending.has(assignmentKey);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", (event) => {
      event.stopPropagation();
      setWorkspaceAssignment(app, version, mode, workspaceId, checkbox.checked);
    });
    const text = document.createElement("span");
    text.textContent = workspace.name || workspaceId;
    label.append(checkbox, text);
    list.append(label);
  });
  section.append(list);
  return section;
}

function renderAppSettings(app, mode, version, installState) {
  const settings = document.createElement("div");
  settings.className = "app-detail-settings";
  const installed = installState.installedCount > 0;
  const isPending = isAppPending(app.app_id);
  const launchable = installed ? installState.launchableCount > 0 : isFrontendLaunchable(app);
  const presentationInstallation = installed ? installState.presentationInstallation : null;
  const pinned = isPinned(app.app_id);

  const shortcutSection = renderDetailSettingsSection("Shortcut");
  const shortcutGrid = renderDetailSettingsGrid();
  shortcutGrid.append(
    renderDetailSettingButton({
      label: pinned ? "Unpin shortcut" : "Pin shortcut",
      icon: "push_pin",
      disabled: isPending || !canTogglePinnedApp(app, installState),
      action: () => togglePinnedApp(app),
    }),
  );
  shortcutSection.append(shortcutGrid);
  if (!launchable) {
    const note = frontendRole(app, presentationInstallation) === "supporting"
      ? "Supporting frontend apps cannot be opened or pinned in the shell."
      : "Apps without a workspace frontend cannot be opened or pinned in the shell.";
    shortcutSection.append(renderDetailSettingsNote(note));
  }
  settings.append(shortcutSection);

  const installSection = renderDetailSettingsSection(mode === "local" ? "Workspace project" : "Installation");
  const installGrid = renderDetailSettingsGrid();
  if (mode === "server") {
    installGrid.append(
      renderDetailSettingButton({
        label: installState.isInstalledEverywhere ? "Uninstall from selected" : "Install in selected",
        icon: installState.isInstalledEverywhere ? "delete" : "download",
        danger: installState.isInstalledEverywhere,
        disabled: !version?.source_id || installState.workspaceCount === 0 || isPending,
        action: () => (installState.isInstalledEverywhere ? uninstallApp(app, version) : installServerApp(app, version)),
      }),
    );
    installSection.append(installGrid);
    settings.append(installSection);

    const sourceSection = renderDetailSettingsSection(sourceKindLabel(app));
    sourceSection.append(renderDetailSettingsNote(version?.version ? `Available source ${version.version}` : "Registered server source"));
    settings.append(sourceSection, renderWorkspaceAssignmentsSettings(app, version, mode));
    return settings;
  }

  if (mode === "local") {
    const invalid = app.localStatus === "invalid";
    installGrid.append(
      renderDetailSettingButton({
        label: installed ? "Uninstall from workspace" : "Install in workspace",
        icon: installed ? "delete" : "download",
        danger: installed,
        disabled: invalid || !app.workspace_id || isPending,
        action: () => (installed ? uninstallLocalApp(app) : installLocalApp(app)),
      }),
    );
    installSection.append(installGrid);
    if (app.workspace_id || app.localStatus) {
      installSection.append(renderDetailSettingsNote(`${app.workspace_id || "workspace"} · ${app.localStatus || "uninstalled"}`));
    }
    settings.append(installSection);

    const distributionSection = renderDetailSettingsSection("Distribution");
    const distributionGrid = renderDetailSettingsGrid();
    distributionGrid.append(
      renderDetailSettingButton({
        label: app.promotion_kind === "update" ? "Push server update" : "Promote to server app",
        icon: "upload",
        disabled: isPending,
        action: () => promoteLocalApp(app),
      }),
      renderDetailSettingButton({
        label: app.has_public_identity ? "Update public app" : "Request public publication",
        icon: "approval",
        disabled: invalid || isPending,
        action: () => requestPublicPublication(app),
      }),
    );
    distributionSection.append(distributionGrid);
    settings.append(distributionSection);

    const dangerSection = renderDetailSettingsSection("Danger zone");
    const dangerGrid = renderDetailSettingsGrid();
    dangerGrid.append(
      renderDetailSettingButton({
        label: "Delete app completely",
        icon: "delete_forever",
        danger: true,
        disabled: !app.can_delete || !app.workspace_id || isPending,
        action: () => deleteLocalApp(app),
      }),
    );
    dangerSection.append(dangerGrid);
    settings.append(dangerSection);
    return settings;
  }

  installGrid.append(
    renderDetailSettingButton({
      label: installState.isInstalledEverywhere ? "Uninstall from selected" : "Install in selected",
      icon: installState.isInstalledEverywhere ? "delete" : "download",
      danger: installState.isInstalledEverywhere,
      disabled: !version?.version || installState.workspaceCount === 0 || isPending,
      action: () => (installState.isInstalledEverywhere ? uninstallApp(app, version) : installApp(app, version)),
    }),
  );
  installSection.append(installGrid);
  settings.append(installSection, renderWorkspaceAssignmentsSettings(app, version, mode));
  return settings;
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
  const pinned = isPinned(app.app_id);
  panel.append(
    renderMenuItem({
      label: pinned ? "Unpin shortcut" : "Pin shortcut",
      icon: "push_pin",
      disabled: isPending || !canTogglePinnedApp(app, installState),
      action: () => togglePinnedApp(app),
    }),
  );
  if (mode === "server") {
    panel.append(
      renderMenuItem({
        label: installState.isInstalledEverywhere ? "Uninstall from selected" : "Install in selected",
        icon: installState.isInstalledEverywhere ? "delete" : "download",
        danger: installState.isInstalledEverywhere,
        disabled: !version?.source_id || installState.workspaceCount === 0 || isPending,
        action: () => (installState.isInstalledEverywhere ? uninstallApp(app, version) : installServerApp(app, version)),
      }),
    );
    const sourceInfo = document.createElement("div");
    sourceInfo.className = "app-row-menu-section";
    const title = document.createElement("p");
    title.className = "app-row-menu-label";
    title.textContent = sourceKindLabel(app);
    sourceInfo.append(title);
    const versionInfo = document.createElement("p");
    versionInfo.className = "app-row-menu-note";
    versionInfo.textContent = version?.version ? `Available source ${version.version}` : "Registered server source";
    sourceInfo.append(versionInfo);
    panel.append(sourceInfo);
    panel.append(renderWorkspaceAssignmentsMenu(app, version, mode));
  } else if (mode === "local") {
    const invalid = app.localStatus === "invalid";
    panel.append(
      renderMenuItem({
        label: installed ? "Uninstall from workspace" : "Install in workspace",
        icon: installed ? "delete" : "download",
        danger: installed,
        disabled: invalid || !app.workspace_id || isPending,
        action: () => (installed ? uninstallLocalApp(app) : installLocalApp(app)),
      }),
    );
    panel.append(
      renderMenuItem({
        label: app.promotion_kind === "update" ? "Push server update" : "Promote to server app",
        icon: "upload",
        disabled: isPending,
        action: () => promoteLocalApp(app),
      }),
    );
    panel.append(
      renderMenuItem({
        label: app.has_public_identity ? "Update public app" : "Request public publication",
        icon: "approval",
        disabled: invalid || isPending,
        action: () => requestPublicPublication(app),
      }),
    );
    panel.append(
      renderMenuItem({
        label: "Delete app completely",
        icon: "delete_forever",
        danger: true,
        disabled: !app.can_delete || !app.workspace_id || isPending,
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

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    });
    reader.addEventListener("error", () => reject(reader.error || new Error("Unable to read ZIP file")));
    reader.readAsDataURL(file);
  });
}

function renderRow(app, mode) {
  const version = latestVersion(app) || { version: app.latest_version || "" };
  const installState = selectedInstallState(app.app_id);
  const canOpen = state.authorityReady && canOpenInstalledApp(app, installState);
  const openWorkspaceId = mode === "local" ? app.workspace_id : installState.launchableWorkspaceId;
  const presentationInstallation = installState.presentationInstallation;
  const row = document.createElement("article");
  row.className = "app-row";
  row.dataset.mode = mode;
  row.dataset.frontendRole = frontendRole(app, presentationInstallation);
  row.title = canOpen ? `Open ${app.name}` : installState.installedCount > 0 ? `${app.name} has no app view` : `${app.name} is not installed`;
  row.addEventListener("click", () => {
    if (canOpen) {
      openApp(app.app_id, openWorkspaceId || null);
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
    if (app.localStatus === "invalid" && app.validation_error) {
      localMeta.title = app.validation_error;
    }
    details.append(localMeta);
  }
  if (mode === "store") {
    const surfaces = document.createElement("span");
    surfaces.className = "app-row-surfaces";
    surfaces.textContent = surfaceLabel(app, presentationInstallation);
    details.append(surfaces);
  }
  if (mode === "server") {
    const serverMeta = document.createElement("span");
    serverMeta.className = "app-row-surfaces";
    serverMeta.textContent = `${sourceKindLabel(app)} · ${surfaceLabel(app, presentationInstallation)}`;
    details.append(serverMeta);
  }

  const actionWrap = document.createElement("div");
  actionWrap.className = "app-row-actions";
  actionWrap.append(renderMoreOptions(app, mode, version, installState));
  const chevron = document.createElement("button");
  chevron.className = "app-row-chevron";
  chevron.type = "button";
  chevron.disabled = !canOpen;
  chevron.setAttribute("aria-label", canOpen ? `Open ${app.name}` : `${app.name} has no app view`);
  const chevronIcon = document.createElement("span");
  chevronIcon.className = "material-symbols-rounded";
  chevronIcon.setAttribute("aria-hidden", "true");
  chevronIcon.textContent = "chevron_right";
  chevron.append(chevronIcon);
  chevron.addEventListener("click", (event) => {
    event.stopPropagation();
    if (canOpen) {
      openApp(app.app_id, openWorkspaceId || null);
    }
  });
  actionWrap.append(chevron);

  row.append(renderAppIcon(app, presentationInstallation), copy, details, actionWrap);
  return row;
}

function knownAppIds() {
  const ids = new Set();
  [state.apps, state.serverApps, state.localApps, state.installations].forEach((items) => {
    items.forEach((item) => {
      if (item?.app_id) {
        ids.add(item.app_id);
      }
    });
  });
  return ids;
}

function stalePinnedAppIds() {
  const known = knownAppIds();
  return state.pinnedApps.filter((appId) => appId && !known.has(appId));
}

function renderStalePinnedShortcut(appId) {
  const app = stalePinnedAppSummary(appId);
  const row = document.createElement("article");
  row.className = "app-row app-row--stale-pin";
  row.dataset.frontendRole = "none";
  const copy = document.createElement("div");
  copy.className = "app-row-copy";
  const title = document.createElement("h3");
  title.textContent = app.name;
  const description = document.createElement("p");
  description.textContent = app.description;
  copy.append(title, description);

  const details = document.createElement("div");
  details.className = "app-row-details";
  const meta = document.createElement("div");
  meta.className = "app-row-meta";
  const status = document.createElement("span");
  status.className = "app-row-status";
  status.dataset.state = "partial";
  status.textContent = "Stale shortcut";
  meta.append(status);
  const surfaces = document.createElement("span");
  surfaces.className = "app-row-surfaces";
  surfaces.textContent = "No matching app source";
  details.append(meta, surfaces);

  const actionWrap = document.createElement("div");
  actionWrap.className = "app-row-actions";
  const action = document.createElement("button");
  action.className = "stale-pin-remove";
  action.type = "button";
  action.disabled = !state.authorityReady || isAppPending(appId);
  action.setAttribute("aria-label", `Remove stale shortcut ${app.name}`);
  const actionLabel = document.createElement("span");
  actionLabel.textContent = "Unpin";
  const actionIcon = document.createElement("span");
  actionIcon.className = "material-symbols-rounded";
  actionIcon.setAttribute("aria-hidden", "true");
  actionIcon.textContent = "keep_off";
  action.append(actionLabel, actionIcon);
  action.addEventListener("click", () => togglePinnedApp(app));
  actionWrap.append(action);

  row.append(renderAppIcon(app), copy, details, actionWrap);
  return row;
}

function renderStalePinnedShortcuts() {
  if (!stalePinsSection || !stalePinList) {
    return;
  }
  const staleAppIds = stalePinnedAppIds();
  stalePinsSection.hidden = staleAppIds.length === 0;
  stalePinList.replaceChildren();
  staleAppIds.forEach((appId) => {
    stalePinList.append(renderStalePinnedShortcut(appId));
  });
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

function renderFeatured() {
  featuredAppsNode.replaceChildren();
  const featured = state.apps.slice(0, 3);
  if (!featured.length) {
    const empty = document.createElement("article");
    empty.className = "feature-card feature-card--empty";
    empty.textContent = "Loading featured apps...";
    featuredAppsNode.append(empty);
    return;
  }
  featured.forEach((app, index) => {
    const card = document.createElement("article");
    card.className = `feature-card feature-card--${index + 1}`;
    const copy = document.createElement("div");
    const category = document.createElement("p");
    const installState = selectedInstallState(app.app_id);
    const presentationInstallation = installState.presentationInstallation;
    category.textContent = categoryLabel(app, presentationInstallation);
    const title = document.createElement("h2");
    title.textContent = app.name || app.app_id;
    const description = document.createElement("span");
    description.textContent = app.description || "Ready to install in Maverick.";
    copy.append(category, title, description);
    const action = document.createElement("button");
    action.className = "feature-link";
    action.type = "button";
    const launchable = installState.installedCount > 0 ? installState.launchableCount > 0 : isFrontendLaunchable(app);
    action.textContent = installState.installedCount > 0 ? (launchable ? "Open" : "Installed") : "Get";
    action.disabled = !state.authorityReady || (installState.installedCount > 0 && !launchable);
    action.addEventListener("click", () => {
      const version = latestVersion(app);
      const currentInstallState = selectedInstallState(app.app_id);
      const currentLaunchable = currentInstallState.installedCount > 0 ? currentInstallState.launchableCount > 0 : isFrontendLaunchable(app);
      if (currentInstallState.installedCount > 0 && currentLaunchable) {
        openApp(app.app_id, currentInstallState.launchableWorkspaceId || null);
      } else if (version) {
        installApp(app, version);
      }
    });
    const icon = renderAppIcon(app, presentationInstallation);
    icon.classList.add("feature-icon");
    card.append(copy, action, icon);
    featuredAppsNode.append(card);
  });
}

function renderStats(filtered) {
  if (!catalogStatsNode) return;
  const surfaces = new Set(state.apps.flatMap((app) => normalizeSurfaces(app)));
  catalogStatsNode.innerHTML = `
    <strong>${state.apps.length}</strong> apps available<br />
    <strong>${surfaces.size}</strong> surfaces supported<br />
    <strong>${filtered.length}</strong> shown now
  `;
}

function renderStore() {
  catalogGrid.replaceChildren();
  const apps = folderCatalogApps();
  renderStats(apps);
  if (!apps.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No apps are available in this workspace yet.";
    catalogGrid.append(empty);
    return;
  }
  if (window.MaverickAppFolderView?.render) {
    window.MaverickAppFolderView.render({
      mount: catalogGrid,
      apps,
      helpers: {
        latestVersion,
        selectedInstallState,
        statusLabel,
        surfaceLabel,
        frontendAvailabilityLabel,
        isFrontendLaunchable,
        canOpenInstalledApp,
        renderAppSettings,
        renderIcon: renderAppIcon,
        installApp,
        installServerApp,
        installLocalApp,
        openApp,
        isAppPending,
      },
    });
    apps.filter((app) => app.storeMode === "local").forEach(loadPublicIdentity);
    return;
  }
  apps.forEach((app) => catalogGrid.append(renderRow(app, app.storeMode || "store")));
}

function renderServer() {
  serverList.replaceChildren();
  if (!state.serverApps.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No server apps are registered on this Maverick installation.";
    serverList.append(empty);
    return;
  }
  state.serverApps.forEach((app) => serverList.append(renderRow(app, "server")));
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
    const summary = localAppSummary(item);
    const row = renderRow(summary, "local");
    row.dataset.localStatus = item.status || "uninstalled";
    localList.append(row);
    loadPublicIdentity(summary);
  });
}

function renderPublicSubmission(submission) {
  publicSubmissionResult.replaceChildren();
  if (!submission) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Enter a submission id to check its public store status.";
    publicSubmissionResult.append(empty);
    return;
  }
  const row = document.createElement("article");
  row.className = "app-row";
  const copy = document.createElement("div");
  copy.className = "app-row-copy";
  const title = document.createElement("h3");
  title.textContent = submission.name || submission.app_id || submission.submission_id;
  const description = document.createElement("p");
  description.textContent = `${submission.submission_id} · ${submission.public_app_uuid || "new public app"}`;
  copy.append(title, description);
  const details = document.createElement("div");
  details.className = "app-row-details";
  const meta = document.createElement("div");
  meta.className = "app-row-meta";
  const versionBadge = document.createElement("span");
  versionBadge.className = "app-row-badge";
  versionBadge.textContent = submission.version || "unknown";
  const status = document.createElement("span");
  status.className = "app-row-status";
  status.dataset.state = submission.status === "published" ? "installed" : "available";
  status.textContent = submission.status || "unknown";
  meta.append(versionBadge, status);
  details.append(meta);
  row.append(renderAppIcon({ app_id: submission.app_id || "public", name: submission.name || submission.app_id || "Public" }), copy, details);
  publicSubmissionResult.append(row);
}

function render() {
  syncLoadingChrome();
  if (state.isLoading && !state.catalogReady) {
    renderLoading();
    return;
  }
  clearLoadingState();
  renderStore();
  renderStalePinnedShortcuts();
}

async function installApp(app, version) {
  if (!state.authorityReady) return;
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
    await refreshServerApps();
    setStatus(`Installed ${app.name}`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(installKey);
    render();
  }
}

async function uninstallApp(app, version) {
  if (!state.authorityReady) return;
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

async function installServerApp(app, version) {
  if (!state.authorityReady) return;
  const workspaceIds = selectedWorkspaceIds();
  const installKey = `${app.app_id}:${version.source_id || version.version || "server"}`;
  state.pending.add(installKey);
  render();
  setStatus(`Installing ${app.name}`, "busy");
  try {
    await requestJson("/api/app-store/install-server", {
      method: "POST",
      body: JSON.stringify({ app_id: app.app_id, source_id: version.source_id, workspace_ids: workspaceIds }),
    });
    await refreshInstallations();
    await refreshServerApps();
    setStatus(`Installed ${app.name}`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(installKey);
    render();
  }
}

async function installLocalApp(app) {
  if (!state.authorityReady) return;
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
    if (isFrontendLaunchable(app)) {
      openApp(app.app_id, workspaceId);
    }
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.pending.delete(pendingKey);
    render();
  }
}

async function uninstallLocalApp(app) {
  if (!state.authorityReady) return;
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
  if (!state.authorityReady) return;
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

async function promoteLocalApp(app) {
  if (!state.authorityReady) return;
  const workspaceId = app.workspace_id;
  if (app.localStatus === "invalid") {
    const detail = app.validation_error || "This local app has an invalid app_contract.json and cannot be promoted.";
    setStatus(detail, "error");
    openPromotionModal({
      title: `Cannot promote ${app.name}`,
      body: detail,
      actions: [
        renderModalButton({ label: "Close", action: closePromotionModal }),
      ],
    });
    return;
  }
  if (!workspaceId) {
    const detail = "Workspace-local app is missing its owner workspace.";
    setStatus(detail, "error");
    openPromotionModal({
      title: `Cannot promote ${app.name}`,
      body: detail,
      actions: [
        renderModalButton({ label: "Close", action: closePromotionModal }),
      ],
    });
    return;
  }
  if (!app.can_promote) {
    const detail = app.promotion_detail || "This workspace-local app cannot be promoted right now.";
    setStatus(detail, "error");
    openPromotionModal({
      title: `Cannot promote ${app.name}`,
      body: detail,
      actions: [
        renderModalButton({ label: "Close", action: closePromotionModal }),
      ],
    });
    return;
  }
  const startPromotion = async (normalizedMode) => {
    closePromotionModal();
    const pendingKey = `${app.app_id}:promote:${normalizedMode}:${workspaceId}`;
    state.pending.add(pendingKey);
    render();
    setStatus(`Promoting ${app.name} as ${normalizedMode}`, "busy");
    try {
      await requestJson("/api/app-store/promote-local", {
        method: "POST",
        body: JSON.stringify({ app_id: app.app_id, workspace_ids: [workspaceId], promotion_mode: normalizedMode }),
      });
      await refreshInstallations();
      await refreshServerApps();
      setStatus(`Promoted ${app.name} as ${normalizedMode}`, "ok");
    } catch (error) {
      setStatus(error.message, "error");
      openPromotionModal({
        title: `Promotion failed for ${app.name}`,
        body: error.message,
        actions: [
          renderModalButton({ label: "Close", action: closePromotionModal }),
        ],
      });
    } finally {
      state.pending.delete(pendingKey);
      render();
    }
  };
  openPromotionModal({
    title: app.promotion_kind === "update" ? `Push server update for ${app.name}` : `Promote ${app.name} to server app`,
    body: app.promotion_kind === "update"
      ? `${app.promotion_detail || `Publish a new server-wide version of ${app.name}.`} The workspace-local copy will remain unchanged.`
      : `${app.promotion_detail || `Choose how to publish ${app.name} from ${workspaceId}.`} The workspace-local copy will remain unchanged.`,
    actions: [
      renderModalButton({ label: "Cancel", action: closePromotionModal }),
      renderModalButton({ label: "As sealed", action: () => startPromotion("sealed") }),
      renderModalButton({ label: "As forkable", intent: "primary", action: () => startPromotion("forkable") }),
    ],
  });
}

function requestPublicPublication(app) {
  if (!state.authorityReady) return;
  let publicationMode = "sealed";
  const modeControl = document.createElement("div");
  modeControl.className = "app-modal__segmented";
  const sealedButton = document.createElement("button");
  sealedButton.type = "button";
  sealedButton.textContent = "Sealed";
  sealedButton.dataset.active = "true";
  const forkableButton = document.createElement("button");
  forkableButton.type = "button";
  forkableButton.textContent = "Forkable";
  const syncMode = () => {
    sealedButton.dataset.active = publicationMode === "sealed" ? "true" : "false";
    forkableButton.dataset.active = publicationMode === "forkable" ? "true" : "false";
  };
  sealedButton.addEventListener("click", () => {
    publicationMode = "sealed";
    syncMode();
  });
  forkableButton.addEventListener("click", () => {
    publicationMode = "forkable";
    syncMode();
  });
  modeControl.append(sealedButton, forkableButton);
  const identityText = document.createElement("p");
  identityText.className = "app-modal__readonly";
  identityText.textContent = app.public_app_uuid
    ? `Public UUID ${app.public_app_uuid}`
    : "A public UUID will be generated and saved into this app's metadata before submission.";
  const sourceText = document.createElement("p");
  sourceText.className = "app-modal__readonly";
  sourceText.textContent = `${app.name || app.app_id} · ${app.app_id} · ${app.latest_version || "unknown version"}`;
  const notesInput = document.createElement("textarea");
  notesInput.placeholder = "Review notes";
  const form = document.createElement("div");
  form.className = "app-modal__form";
  form.append(
    renderModalField("Public identity", identityText),
    renderModalField("Source app", sourceText),
    renderModalField("Publication mode", modeControl),
    renderModalField("Notes", notesInput),
  );
  promotionModalTitle.textContent = app.public_app_uuid ? `Update public app` : `Request public publication`;
  promotionModalBody.replaceChildren(form);
  promotionModalActions.replaceChildren(
    renderModalButton({ label: "Cancel", action: closePromotionModal }),
    renderModalButton({
      label: "Submit request",
      intent: "primary",
      action: async () => {
        const pendingKey = `${app.app_id}:public-submit`;
        state.pending.add(pendingKey);
        render();
        setStatus(`Packaging and submitting ${app.name} to public store`, "busy");
        try {
          const payload = await requestJson("/api/apps/app-store/backend", {
            method: "POST",
            body: JSON.stringify({
              action: "public_submissions.create",
              source_kind: "workspace_local",
              source_app_id: app.app_id,
              source_workspace_id: app.workspace_id,
              publication_mode: publicationMode,
              notes: notesInput.value.trim(),
            }),
          });
          const submissionId = payload.submission?.submission_id || "submitted";
          if (payload.submission?.public_app_uuid) {
            state.publicIdentities[`${app.workspace_id || ""}:${app.app_id}`] = {
              public_app_uuid: payload.submission.public_app_uuid,
              has_public_identity: true,
            };
          }
          closePromotionModal();
          setStatus(`Public publication request ${submissionId} submitted`, "ok");
        } catch (error) {
          setStatus(error.message, "error");
        } finally {
          state.pending.delete(pendingKey);
          render();
        }
      },
    }),
  );
  promotionModal.classList.remove("is-hidden");
  promotionModal.setAttribute("aria-hidden", "false");
  requestJson("/api/apps/app-store/backend", {
    method: "POST",
    body: JSON.stringify({
      action: "public_submissions.identity",
      source_kind: "workspace_local",
      source_app_id: app.app_id,
      source_workspace_id: app.workspace_id,
    }),
  }).then((payload) => {
    const identity = payload.identity || {};
    if (identity.public_app_uuid) {
      identityText.textContent = `Public UUID ${identity.public_app_uuid}`;
      state.publicIdentities[`${app.workspace_id || ""}:${app.app_id}`] = identity;
    }
  }).catch(() => null);
}

async function loadPublicIdentity(app) {
  if (!app.workspace_id || !app.app_id || app.localStatus === "invalid") return;
  const key = `${app.workspace_id}:${app.app_id}`;
  if (state.publicIdentities[key] || state.pending.has(`${app.app_id}:public-identity:${app.workspace_id}`)) return;
  state.pending.add(`${app.app_id}:public-identity:${app.workspace_id}`);
  try {
    const payload = await requestJson("/api/apps/app-store/backend", {
      method: "POST",
      body: JSON.stringify({
        action: "public_submissions.identity",
        source_kind: "workspace_local",
        source_app_id: app.app_id,
        source_workspace_id: app.workspace_id,
      }),
    });
    state.publicIdentities[key] = payload.identity || {};
    if (state.publicIdentities[key].public_app_uuid) {
      render();
    }
  } catch (_error) {
    state.publicIdentities[key] = { public_app_uuid: "", has_public_identity: false };
  } finally {
    state.pending.delete(`${app.app_id}:public-identity:${app.workspace_id}`);
  }
}

async function setWorkspaceAssignment(app, version, mode, workspaceId, shouldInstall) {
  if (!state.authorityReady) return;
  const assignmentKey = `${app.app_id}:${version.source_id || version.version || "server"}:${workspaceId}`;
  state.pending.add(assignmentKey);
  render();
  setStatus(`${shouldInstall ? "Assigning" : "Removing"} ${app.name}`, "busy");
  try {
    const installEndpoint = mode === "server" ? "/api/app-store/install-server" : "/api/app-store/install";
    await requestJson(shouldInstall ? installEndpoint : "/api/app-store/uninstall", {
      method: "POST",
      body: JSON.stringify({
        app_id: app.app_id,
        version: version.version,
        source_id: version.source_id,
        workspace_ids: [workspaceId],
      }),
    });
    if (mode === "server") {
      await refreshServerApps();
    }
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

async function refreshServerApps() {
  const payload = await requestJson("/api/app-store/server-apps");
  state.serverApps = payload.items || [];
}

async function refreshPinnedApps() {
  const payload = await requestJson("/api/apps/app-store/backend", {
    method: "POST",
    body: JSON.stringify({ action: "pinned_apps.list" }),
  });
  state.pinnedApps = payload.pinned_apps || [];
}

async function togglePinnedApp(app) {
  if (!state.authorityReady) return;
  const installState = selectedInstallState(app.app_id);
  if (!canTogglePinnedApp(app, installState)) {
    setStatus(`${app.name || app.app_id} has no app view to pin`, "error");
    return;
  }
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

async function lookupPublicSubmission() {
  const submissionId = publicSubmissionId.value.trim();
  if (!submissionId) {
    renderPublicSubmission(null);
    return;
  }
  setStatus(`Checking ${submissionId}`, "busy");
  try {
    const payload = await requestJson("/api/apps/app-store/backend", {
      method: "POST",
      body: JSON.stringify({ action: "public_submissions.read", submission_id: submissionId }),
    });
    renderPublicSubmission(payload.submission);
    setStatus(`Public request ${submissionId} loaded`, "ok");
  } catch (error) {
    publicSubmissionResult.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = error.message;
    publicSubmissionResult.append(empty);
    setStatus(error.message, "error");
  }
}

async function refreshCatalog() {
  const result = await loadCachedCatalog();
  applyCatalog(result.payload);
  state.catalogReady = true;
  render();
  void result.revalidation?.then((next) => {
    if (!next.changed) return;
    applyCatalog(next.payload);
    render();
  }).catch(() => undefined);
  return result.payload;
}

async function load() {
  state.isLoading = true;
  state.catalogReady = false;
  state.authorityReady = false;
  setStatus("Loading", "busy");
  render();
  try {
    const catalogRead = refreshCatalog();
    const [workspaces, catalog, serverApps, installations, pinned] = await Promise.all([
      requestJson("/api/workspaces"),
      catalogRead,
      requestJson("/api/app-store/server-apps"),
      requestJson("/api/app-store/installations"),
      requestJson("/api/apps/app-store/backend", {
        method: "POST",
        body: JSON.stringify({ action: "pinned_apps.list" }),
      }),
    ]);
    state.workspaces = workspaces.items || [];
    state.serverApps = serverApps.items || [];
    state.catalogApps = catalog.items || [];
    state.apps = mergeCatalogAndServerApps(state.catalogApps, state.serverApps);
    state.installations = installations.items || [];
    state.localApps = installations.local_apps || [];
    state.pinnedApps = pinned.pinned_apps || [];
    state.selectedWorkspaces = new Set([workspaces.active_workspace_id || state.workspaces[0]?.workspace_id].filter(Boolean));
    state.authorityReady = true;
    state.isLoading = false;
    renderWorkspaces();
    render();
    setStatus("Ready", "ok");
  } catch (error) {
    state.isLoading = false;
    renderWorkspaces();
    render();
    throw error;
  }
}

navigationButtons.forEach((button) => {
  button.addEventListener("click", () => {
    navigationButtons.forEach((node) => node.classList.remove("is-active"));
    button.classList.add("is-active");
    document.querySelector(`#${button.dataset.target || "today"}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

document.querySelectorAll(".quick-link").forEach((button) => {
  button.addEventListener("click", () => {
    if (!surfaceNode || !searchNode) return;
    surfaceNode.value = button.dataset.filterSurface || "";
    searchNode.value = "";
    render();
    document.querySelector("#catalog")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

searchNode?.addEventListener("input", render);
surfaceNode?.addEventListener("change", render);

publicSubmissionLookup?.addEventListener("click", lookupPublicSubmission);
publicSubmissionId?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    lookupPublicSubmission();
  }
});

document.addEventListener("click", () => closeOpenMenus());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeOpenMenus();
    closePromotionModal();
  }
});
promotionModalClose?.addEventListener("click", closePromotionModal);
promotionModal?.addEventListener("click", (event) => {
  if (event.target === promotionModal) {
    closePromotionModal();
  }
});

window.addEventListener("message", (event) => {
  if (!isExactMaverickParentMessage(event)) return;
  const payload = event.data;
  if (payload?.type === "maverick.app.data-changed" && payload.owner_app_id === "app-store"
      && ["records", "catalog"].includes(payload.resource)) {
    // Display recovery cannot confer installation or workspace authority.
    refreshCatalog().catch(() => undefined);
  }
});

load().catch((error) => {
  setStatus(error.message, "error");
});
